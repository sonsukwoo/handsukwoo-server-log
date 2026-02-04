import subprocess
import logging
import re
from datetime import datetime
from src.database.connection import SessionLocal
from .models import CloudflareTunnel

logger = logging.getLogger("CLOUDFLARE")

def collect_cloudflare_status(ts=None, batch_id=None):
    """
    Checks Cloudflare Tunnel status.
    """
    try:
        # Try to get tunnel info. If cert is missing, this might fail,
        # but we can at least try 'version' or handled output.
        result = subprocess.run(['cloudflared', 'tunnel', 'list'], capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            # Handle the case where cert is missing or auth is needed
            if "client didn't specify origincert path" in result.stderr:
                logger.warning("Cloudflare cert missing. Skipping tunnel list.")
                return None
            logger.error(f"Cloudflare tunnel list failed: {result.stderr}")
            return None

        # If we have output, parse it
        lines = result.stdout.strip().split('\n')
        # Typical output has header
        if len(lines) < 2: return "Cloudflare: No tunnels found"

        db = SessionLocal()
        count = 0
        try:
            for line in lines[1:]: # Skip header
                parts = re.split(r'\s{2,}', line.strip())
                if len(parts) >= 4:
                    id_, name, status, connections = parts[0], parts[1], parts[2], parts[3]
                    new_tunnel = CloudflareTunnel(
                        ts=ts or datetime.now(),
                        tunnel_name=name,
                        status=status,
                        error_message=connections if "active" not in status.lower() else ""
                    )
                    db.add(new_tunnel)
                    count += 1
            db.commit()
            return f"Cloudflare: {count} tunnels monitored"
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving cloudflare status: {e}")
            return None
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Cloudflare status check error: {e}")
        return None
