import subprocess
import logging
import json
from datetime import datetime
from src.database.connection import SessionLocal
from .models import SystemEvent

logger = logging.getLogger("SYSTEM_EVENT")

def collect_system_events(ts=None, batch_id=None):
    """
    Collects system events from journalctl in JSON format.
    """
    # Use journalctl with JSON output for better parsing
    cmd = ['journalctl', '-n', '50', '--no-pager', '-o', 'json']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')
    except Exception as e:
        logger.warning(f"journalctl failed, falling back to basic tail: {e}")
        try:
            result = subprocess.run(['tail', '-n', '50', '/var/log/syslog'], capture_output=True, text=True, check=True)
            lines = result.stdout.strip().split('\n')
            return parse_basic_syslog(lines, ts)
        except Exception as e2:
            logger.error(f"Failed to collect system logs: {e2}")
            return None

    db = SessionLocal()
    count = 0
    try:
        for line in lines:
            if not line.strip(): continue
            try:
                data = json.loads(line)
                # PRIORITY: 0 (emerg) to 7 (debug)
                prio = int(data.get('PRIORITY', 6))
                severity = ["EMERG", "ALERT", "CRIT", "ERR", "WARNING", "NOTICE", "INFO", "DEBUG"][prio]
                
                # Timestamp in microseconds
                msg_ts = datetime.fromtimestamp(int(data.get('__REALTIME_TIMESTAMP', 0)) / 1_000_000)
                
                new_event = SystemEvent(
                    ts=msg_ts,
                    event_type="journal",
                    severity=severity,
                    source=data.get('SYSLOG_IDENTIFIER', 'unknown'),
                    message=data.get('MESSAGE', '')
                )
                db.add(new_event)
                count += 1
            except Exception:
                continue
        
        db.commit()
        if count > 0:
            logger.info(f"System events saved: {count} entries")
            return f"System: {count} events collected"
        return "System: 0 events"
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving system events: {e}")
        return None
    finally:
        db.close()

def parse_basic_syslog(lines, ts):
    # Basic fallback parsing logic
    db = SessionLocal()
    count = 0
    try:
        for line in lines:
            if not line.strip(): continue
            new_event = SystemEvent(
                ts=ts or datetime.now(),
                event_type="syslog",
                severity="INFO",
                source="system",
                message=line.strip()
            )
            db.add(new_event)
            count += 1
        db.commit()
        return f"System: {count} events collected (fallback)"
    except Exception as e:
        db.rollback()
        return None
    finally:
        db.close()
