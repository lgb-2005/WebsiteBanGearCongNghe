"""Chạy bộ câu hỏi đánh giá chatbot và xuất metrics.

Usage:
    python manage.py chatbot_eval --output eval_result.json
"""

import json
import statistics
import time
from pathlib import Path

from django.core.management.base import BaseCommand

from chatbot.context import ChatContext
from chatbot import throttling as throttling_module
from chatbot.engine import ChatEngine
from chatbot.models import Conversation
from chatbot.providers.gemini import GeminiProvider


BASE_DIR = Path(__file__).resolve().parent.parent.parent / 'eval'


def _load_questions(path=None):
    path = Path(path) if path else BASE_DIR / 'questions.json'
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)['questions']


class Command(BaseCommand):
    help = 'Chạy bộ câu hỏi đánh giá chatbot và xuất metrics.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--questions',
            type=str,
            help='Đường dẫn file JSON chứa câu hỏi (mặc định chatbot/eval/questions.json).',
        )
        parser.add_argument(
            '--output',
            type=str,
            default='chatbot_eval_result.json',
            help='File JSON lưu kết quả chi tiết (mặc định chatbot_eval_result.json).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Chỉ chạy N câu hỏi đầu tiên.',
        )
        parser.add_argument(
            '--delay',
            type=int,
            default=15,
            help='Nghỉ giữa các câu hỏi (giây) để tránh quota. Mặc định 15.',
        )

    def handle(self, *args, **options):
        # Tắt rate limit trong quá trình đánh giá để không bị chặn.
        original_limit = throttling_module.RATE_LIMIT_PER_HOUR
        throttling_module.RATE_LIMIT_PER_HOUR = 0

        questions = _load_questions(options['questions'])
        if options['limit']:
            questions = questions[:options['limit']]

        engine = ChatEngine(provider=GeminiProvider(retry_quota=True))
        results = []

        for idx, item in enumerate(questions):
            conversation = Conversation.objects.create(
                user=None,
                session_id=f'eval-{item["id"]}',
            )
            ctx = ChatContext(user=None, session_id=conversation.session_id)

            try:
                response = engine.process(
                    message=item['text'],
                    conversation=conversation,
                    ctx=ctx,
                    page_context=item.get('page_context'),
                )
                status = 'ok'
                error = ''
            except Exception as exc:
                response = {}
                status = 'exception'
                error = str(exc)

            actual_tools = response.get('meta', {}).get('tools', [])
            record = {
                'id': item['id'],
                'question': item['text'],
                'intent': item.get('intent'),
                'expected_tool': item.get('expected_tool'),
                'actual_tools': actual_tools,
                'tool_match': (item.get('expected_tool') in actual_tools) if item.get('expected_tool') else None,
                'loop_rounds': response.get('meta', {}).get('loop_rounds', 0),
                'latency_ms': response.get('meta', {}).get('latency_ms', 0),
                'product_count': len(response.get('products') or []),
                'reply': response.get('reply', ''),
                'status': status,
                'error': error,
            }
            results.append(record)
            self.stdout.write(f"[{item['id']}/{len(questions)}] {status} | tools={actual_tools} | latency={record['latency_ms']}ms")

            if options['delay'] and idx < len(questions) - 1:
                time.sleep(options['delay'])

        throttling_module.RATE_LIMIT_PER_HOUR = original_limit

        metrics = self._compute_metrics(results)
        summary = {
            'total': len(questions),
            'metrics': metrics,
            'results': results,
        }

        output_path = Path(options['output'])
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.SUCCESS('\n=== METRICS ==='))
        for key, value in metrics.items():
            self.stdout.write(f"  {key}: {value}")
        self.stdout.write(self.style.SUCCESS(f'\nKết quả chi tiết đã lưu vào {output_path}'))

    def _compute_metrics(self, results):
        latencies = [r['latency_ms'] for r in results if r['status'] == 'ok']
        loop_rounds = [r['loop_rounds'] for r in results]

        tool_results = [r for r in results if r['expected_tool'] is not None]
        tool_correct = sum(1 for r in tool_results if r['tool_match'])
        tool_accuracy = tool_correct / len(tool_results) if tool_results else None

        clarify_count = sum(1 for r in results if r['intent'] == 'clarify' and r['loop_rounds'] == 0)
        clarify_total = sum(1 for r in results if r['intent'] == 'clarify')

        no_result_results = [r for r in results if r['intent'] == 'no_result_recovery']
        recovery_success = sum(1 for r in no_result_results if r['product_count'] > 0)

        avg_latency = statistics.mean(latencies) if latencies else 0
        p50 = statistics.median(latencies) if latencies else 0
        p95 = self._percentile(latencies, 95) if len(latencies) >= 2 else (latencies[0] if latencies else 0)

        return {
            'tool_accuracy': round(tool_accuracy, 3) if tool_accuracy is not None else None,
            'avg_latency_ms': round(avg_latency, 1),
            'p50_latency_ms': round(p50, 1),
            'p95_latency_ms': round(p95, 1),
            'avg_loop_rounds': round(statistics.mean(loop_rounds), 2) if loop_rounds else 0,
            'clarify_success_rate': round(clarify_count / clarify_total, 3) if clarify_total else None,
            'no_result_recovery_success_rate': round(recovery_success / len(no_result_results), 3) if no_result_results else None,
            'exception_count': sum(1 for r in results if r['status'] != 'ok'),
        }

    @staticmethod
    def _percentile(values, percentile):
        sorted_values = sorted(values)
        k = (len(sorted_values) - 1) * (percentile / 100)
        f = int(k)
        c = min(f + 1, len(sorted_values) - 1)
        if f == c:
            return sorted_values[f]
        return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])
