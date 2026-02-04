import subprocess
import logging
import re
from datetime import datetime
from src.database.connection import SessionLocal
from .models import LoginEvent

logger = logging.getLogger("AUTH")

def parse_last_output(line):
    """
    Parses a single line from 'last' output.
    Example: handsukw pts/0        192.168.219.31   Wed Feb  4 11:02   still logged in
    """
    # Pattern to match User, TTY, Host, Day, Month, Date, Time
    # Note: last output can vary, but this is a common format on Ubuntu
    pattern = r"^(\S+)\s+(\S+)\s+(\S+)\s+(\w{3})\s+(\w{3})\s+(\d+)\s+(\d{2}:\d{2})"
    match = re.match(pattern, line)
    if not match:
        return None

    user, tty, host, day, month_str, date, time_str = match.groups()
    
    # Skip pseudo entries like 'reboot', 'wtmp'
    if user in ['reboot', 'wtmp']:
        return None

    # Resolve month and year
    current_year = datetime.now().year
    try:
        ts_str = f"{month_str} {date} {time_str} {current_year}"
        ts = datetime.strptime(ts_str, "%b %d %H:%M %Y")
        
        # If the parsed date is in the future, it's likely from last year
        if ts > datetime.now():
            ts = ts.replace(year=current_year - 1)
    except ValueError:
        return None

    return {
        "user_name": user,
        "tty": tty,
        "remote_host": host,
        "ts": ts
    }

def collect_auth_logs(ts=None, batch_id=None):
    """
    Collects system login/auth records using the 'last' command.
    """
    try:
        result = subprocess.run(['last', '-i', '-n', '50'], capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')
    except Exception as e:
        logger.error(f"Failed to run 'last' command: {e}")
        return None

    db = SessionLocal()
    count = 0
    try:
        for line in lines:
            data = parse_last_output(line)
            if not data:
                continue

            # Check for duplicates (simple check based on timestamp, user, and tty)
            exists = db.query(LoginEvent).filter(
                LoginEvent.ts == data['ts'],
                LoginEvent.user_name == data['user_name'],
                LoginEvent.tty == data['tty']
            ).first()

            if not exists:
                new_event = LoginEvent(
                    ts=data['ts'],
                    user_name=data['user_name'],
                    tty=data['tty'],
                    remote_host=data['remote_host']
                )
                db.add(new_event)
                count += 1

        db.commit()
        if count > 0:
            logger.info(f"Auth logs saved: {count} new login events")
            return f"Auth: {count} new logins collected"
        return "Auth: 0 new logins"
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving auth logs: {e}")
        return None
    finally:
        db.close()
