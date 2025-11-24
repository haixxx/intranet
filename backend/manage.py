#!/usr/bin/env python
import os
import sys

def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'appserver.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Không thể import Django. Kiểm tra đã cài đặt trong venv chưa?"
        ) from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()