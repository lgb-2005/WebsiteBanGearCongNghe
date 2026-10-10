"""Đối chiếu alias với DB THẬT để phát hiện alias chết.

Không thể làm việc này bằng unit test vì test chạy trên DB rỗng.

    python manage.py chatbot_check_aliases
"""

from django.core.management.base import BaseCommand

from chatbot.intent.aliases import (
    ATTRIBUTE_ALIASES,
    CATEGORY_ALIASES,
    BOOLEAN_LIKE_GROUPS,
    CLEAN_GROUPS,
    DIRTY_GROUPS,
    USABLE_GROUPS,
)
from products.models import AttributeGroup, AttributeValue, Category


class Command(BaseCommand):
    help = 'Kiểm tra mọi slug trong aliases.py có tồn tại trong DB hay không'

    def handle(self, *args, **options):
        existing_pairs = set(
            AttributeValue.objects.filter(
                is_active=True,
                group__is_active=True,
            ).values_list('group__slug', 'slug')
        )
        existing_groups = set(AttributeGroup.objects.values_list('slug', flat=True))
        existing_categories = set(Category.objects.values_list('slug', flat=True))

        problems = 0

        self.stdout.write(self.style.MIGRATE_HEADING('1. Category alias'))
        for category_slug in CATEGORY_ALIASES:
            if category_slug in existing_categories:
                self.stdout.write(f'   OK    {category_slug}')
            else:
                problems += 1
                self.stdout.write(self.style.ERROR(f'   CHET  {category_slug} (không có trong DB)'))

        self.stdout.write(self.style.MIGRATE_HEADING('2. Attribute alias'))
        for alias_key, spec in ATTRIBUTE_ALIASES.items():
            dead = []
            for group_slug, value_slugs in spec['attributes'].items():
                if group_slug not in existing_groups:
                    dead.append(f'{group_slug}:* (group không tồn tại)')
                    continue
                for value_slug in value_slugs:
                    if (group_slug, value_slug) not in existing_pairs:
                        dead.append(f'{group_slug}:{value_slug}')

            if dead:
                problems += len(dead)
                self.stdout.write(self.style.WARNING(f'   {alias_key}: {", ".join(dead)}'))
            else:
                self.stdout.write(f'   OK    {alias_key}')

        self.stdout.write(self.style.MIGRATE_HEADING('3. Phân loại chất lượng group'))

        classified = {
            'CLEAN': CLEAN_GROUPS,
            'USABLE': USABLE_GROUPS,
            'BOOLEAN': set(BOOLEAN_LIKE_GROUPS),
            'DIRTY': DIRTY_GROUPS,
        }

        all_classified = set()
        for label, group_slugs in classified.items():
            overlap = all_classified & group_slugs
            if overlap:
                problems += len(overlap)
                self.stdout.write(self.style.ERROR(
                    f'   TRUNG {label} bị xếp 2 nhóm: {", ".join(sorted(overlap))}'
                ))

            dead = group_slugs - existing_groups
            if dead:
                problems += len(dead)
                self.stdout.write(self.style.ERROR(
                    f'   CHET  {label}: {", ".join(sorted(dead))}'
                ))
            else:
                self.stdout.write(f'   OK    {label} ({len(group_slugs)} group)')

            all_classified |= group_slugs

        unclassified = existing_groups - all_classified
        if unclassified:
            problems += len(unclassified)
            self.stdout.write(self.style.ERROR(
                f'   THIEU chưa phân loại: {", ".join(sorted(unclassified))}'
            ))
        else:
            self.stdout.write(
                f'   OK    phủ hết {len(existing_groups)} group trong DB'
            )

        self.stdout.write('')
        if problems:
            self.stdout.write(self.style.ERROR(f'Phát hiện {problems} vấn đề cần sửa trong aliases.py'))
        else:
            self.stdout.write(self.style.SUCCESS('Toàn bộ alias khớp với DB'))
