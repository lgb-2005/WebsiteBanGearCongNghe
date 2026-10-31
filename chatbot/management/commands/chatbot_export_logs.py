"""Xuất ChatTurnLog ra CSV/JSON để phân tích metrics cho khóa luận.

Usage:
    python manage.py chatbot_export_logs --since 2026-10-01 --format csv --output chatbot_logs.csv
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand

from chatbot.models import ChatTurnLog


def _percentile(sorted_values, pct):
    if not sorted_values:
        return 0
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return int(round(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)))


def compute_log_metrics(rows):
    total = len(rows)
    if not total:
        return {
            'total_turns': 0,
            'ok_turns': 0,
            'p50_latency_ms': 0,
            'p95_latency_ms': 0,
            'avg_latency_ms': 0,
            'min_latency_ms': 0,
            'max_latency_ms': 0,
            'avg_loop_rounds': 0.0,
            'total_prompt_tokens': 0,
            'total_completion_tokens': 0,
            'avg_prompt_tokens': 0,
            'avg_completion_tokens': 0,
        }

    ok_rows = [r for r in rows if r.get('status') == ChatTurnLog.STATUS_OK]
    target_rows = ok_rows or rows
    latencies = sorted(int(r.get('latency_ms') or 0) for r in target_rows)
    rounds = [int(r.get('loop_rounds') or 0) for r in target_rows]
    prompt_tokens = [int(r.get('prompt_tokens') or 0) for r in rows if r.get('prompt_tokens') is not None]
    completion_tokens = [int(r.get('completion_tokens') or 0) for r in rows if r.get('completion_tokens') is not None]

    return {
        'total_turns': total,
        'ok_turns': len(ok_rows),
        'p50_latency_ms': _percentile(latencies, 50),
        'p95_latency_ms': _percentile(latencies, 95),
        'avg_latency_ms': int(round(sum(latencies) / len(latencies))) if latencies else 0,
        'min_latency_ms': latencies[0] if latencies else 0,
        'max_latency_ms': latencies[-1] if latencies else 0,
        'avg_loop_rounds': round(sum(rounds) / len(rounds), 2) if rounds else 0.0,
        'total_prompt_tokens': sum(prompt_tokens),
        'total_completion_tokens': sum(completion_tokens),
        'avg_prompt_tokens': int(round(sum(prompt_tokens) / len(prompt_tokens))) if prompt_tokens else 0,
        'avg_completion_tokens': int(round(sum(completion_tokens) / len(completion_tokens))) if completion_tokens else 0,
    }


class Command(BaseCommand):
    help = 'Xuat ChatTurnLog ra CSV/JSON de phan tich metrics.'

    def add_arguments(self, parser):
        parser.add_argument('--since', type=str, help='Ngay bat dau YYYY-MM-DD.')
        parser.add_argument('--until', type=str, help='Ngay ket thuc YYYY-MM-DD.')
        parser.add_argument('--format', type=str, choices=['csv', 'json'], default='csv')
        parser.add_argument('--output', type=str, default='chatbot_logs.csv')

    def handle(self, *args, **options):
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        qs = ChatTurnLog.objects.all()
        if options['since']:
            qs = qs.filter(created_at__date__gte=datetime.strptime(options['since'], '%Y-%m-%d').date())
        if options['until']:
            qs = qs.filter(created_at__date__lte=datetime.strptime(options['until'], '%Y-%m-%d').date())

        qs = qs.order_by('-created_at')
        rows = list(qs.values(
            'id', 'conversation_id', 'user_message', 'resolved_aliases',
            'tool_calls', 'loop_rounds', 'provider', 'model_name',
            'prompt_tokens', 'completion_tokens', 'latency_ms',
            'final_answer', 'status', 'error_detail', 'created_at',
        ))

        output_path = Path(options['output'])
        if options['format'] == 'json':
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
        else:
            with open(output_path, 'w', encoding='utf-8', newline='') as f:
                if rows:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)

        metrics = compute_log_metrics(rows)
        self.stdout.write(self.style.SUCCESS(f'Da xuat {len(rows)} log ra {output_path}'))
        self.stdout.write(
            f"--- Thong ke Metrics ({metrics['ok_turns']}/{metrics['total_turns']} luot OK) ---\n"
            f"Latency (ms): p50={metrics['p50_latency_ms']}ms | p95={metrics['p95_latency_ms']}ms | "
            f"avg={metrics['avg_latency_ms']}ms | min={metrics['min_latency_ms']}ms | max={metrics['max_latency_ms']}ms\n"
            f"So vong loop trung binh: {metrics['avg_loop_rounds']}\n"
            f"Token usage: prompt_total={metrics['total_prompt_tokens']} (avg={metrics['avg_prompt_tokens']}) | "
            f"completion_total={metrics['total_completion_tokens']} (avg={metrics['avg_completion_tokens']})"
        )
