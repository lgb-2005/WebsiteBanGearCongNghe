"""Xuất ChatTurnLog ra CSV/JSON để phân tích metrics cho khóa luận.

Usage:
    python manage.py chatbot_export_logs --since 2026-10-01 --format csv --output chatbot_logs.csv
"""

import csv
import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand

from chatbot.models import ChatTurnLog


class Command(BaseCommand):
    help = 'Xuat ChatTurnLog ra CSV/JSON de phan tich metrics.'

    def add_arguments(self, parser):
        parser.add_argument('--since', type=str, help='Ngay bat dau YYYY-MM-DD.')
        parser.add_argument('--until', type=str, help='Ngay ket thuc YYYY-MM-DD.')
        parser.add_argument('--format', type=str, choices=['csv', 'json'], default='csv')
        parser.add_argument('--output', type=str, default='chatbot_logs.csv')

    def handle(self, *args, **options):
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

        self.stdout.write(self.style.SUCCESS(f'Da xuat {len(rows)} log ra {output_path}'))
