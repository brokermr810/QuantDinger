
import os
import sys
import logging
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

# Load environment variables from .env file with explicit UTF-8 encoding
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.env"))
print(f"Loading .env from: {env_path}")
load_dotenv(env_path, encoding='utf-8', override=True)

# DEBUG: Check DATABASE_URL
db_url = os.getenv("DATABASE_URL")
if db_url:
    # Mask password for safety but show repr to check for invisible chars
    safe_url = db_url
    if "@" in safe_url:
        part1, part2 = safe_url.rsplit("@", 1)
        if ":" in part1:
            u, p = part1.split(":", 1)
            # keep first 3 chars of password if possible
            safe_p = p[:3] + "***" if len(p) > 3 else "***"
            safe_url = f"{u}:{safe_p}@{part2}"
    print(f"DEBUG: DATABASE_URL repr: {repr(db_url)}")  # repr will show \xb2 if present
    print(f"DEBUG: Safe DATABASE_URL: {safe_url}")
else:
    print("DEBUG: DATABASE_URL is NOT set in environment.")

from app.services.pending_order_worker import PendingOrderWorker
from app.utils.db import get_db_connection
from app.services.exchange_execution import load_strategy_configs, resolve_exchange_config
from app.services.live_trading.factory import create_client

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_real_sync_binance():
    logger.info(">>> Starting REAL Binance Position Sync Test")
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        probe_id = None
        strategy_id = None
        
        try:
            # 1. Find a suitable LIVE Binance strategy
            logger.info("Searching for a 'live' Binance strategy in database...")
            cur.execute("""
                SELECT id, user_id, strategy_name, exchange_config 
                FROM qd_strategies_trading 
                WHERE execution_mode = 'live' 
                  AND status = 'running'
                  AND (exchange_config::text ILIKE '%binance%' OR exchange_config::text ILIKE '%exchange_id":"binance"%')
                LIMIT 1
            """)
            row = cur.fetchone()
            
            if not row:
                logger.error("No active LIVE Binance strategy found in qd_strategies_trading.")
                logger.info("Please create a strategy with execution_mode='live' and exchange_id='binance' first.")
                return

            strategy_id = row['id']
            strategy_name = row['strategy_name']
            user_id = row.get('user_id') or 1
            logger.info(f"Found Strategy ID: {strategy_id} Name: {strategy_name} UserID: {user_id}")
            
            # Load full config
            cfg = load_strategy_configs(strategy_id)
            exchange_config = resolve_exchange_config(cfg.get("exchange_config") or {})
            market_type = cfg.get("market_type", "swap")

            # 2. Inspect Real Exchange Positions
            logger.info("--- Connecting to Exchange to fetch REAL positions ---")
            try:
                client = create_client(exchange_config, market_type=market_type)
                # For Binance futures, get_positions returns list of dicts
                positions_resp = client.get_positions()
                
                real_positions_map = {}
                positions_list = []

                if isinstance(positions_resp, list):
                    positions_list = positions_resp
                elif isinstance(positions_resp, dict):
                    # Handle case where client implementation wraps list in {'raw': [...]} or similar
                    if "raw" in positions_resp and isinstance(positions_resp["raw"], list):
                        positions_list = positions_resp["raw"]
                    else:
                        logger.warning(f"Unexpected dict structure from get_positions: keys={list(positions_resp.keys())}")
                        logger.debug(f"Response: {positions_resp}")
                
                if positions_list:
                    logger.info(f"Exchange returned {len(positions_list)} position entries.")
                    for p in positions_list:
                        amt = float(p.get("positionAmt") or 0.0)
                        sym = p.get("symbol")
                        if abs(amt) > 0:
                            logger.info(f"REAL POSITION: {sym} | Amt: {amt} | Entry: {p.get('entryPrice')}")
                            real_positions_map[sym] = amt
                    if not real_positions_map:
                        logger.info("No open positions found on exchange (all amts are 0).")
                else:
                    if not isinstance(positions_resp, list) and not (isinstance(positions_resp, dict) and "raw" in positions_resp):
                         logger.warning("Could not extract positions list from response.")

            except Exception as e:
                logger.error(f"Failed to fetch real positions from exchange: {e}")
                # We continue mostly to test the sync logic itself, even if fetch failed (though sync will likely fail too)

            # 3. Insert or Identify Probe Position
            logger.info("--- Checking Local DB Positions ---")
            
            # Check for ANY existing positions for this strategy
            cur.execute("SELECT * FROM qd_strategy_positions WHERE strategy_id = %s", (strategy_id,))
            existing_rows = cur.fetchall()
            
            if existing_rows:
                logger.info(f"Found {len(existing_rows)} existing positions in DB.")
                for r in existing_rows:
                    logger.info(f"DB POS: ID={r['id']} {r['symbol']} {r['side']} Size={r['size']}")
                # Use the first one as probe if available, or just insert the specific BTC/USDT probe
                # Let's check specifically for BTC/USDT as our probe target
                cur.execute("SELECT id FROM qd_strategy_positions WHERE strategy_id = %s AND symbol = 'BTC/USDT'", (strategy_id,))
                probe_row = cur.fetchone()
                if probe_row:
                    probe_id = probe_row['id']
                    logger.info(f"Using existing BTC/USDT position as probe (ID: {probe_id})")
            
            if not probe_id:
                # Insert a ghost position to see if it gets cleared
                # Note: schema has user_id and updated_at, but NO created_at
                logger.info("Inserting a GHOST PROBE position (BTC/USDT, size=0.0001) to test sync...")
                cur.execute("""
                    INSERT INTO qd_strategy_positions
                    (user_id, strategy_id, symbol, side, size, entry_price, updated_at)
                    VALUES (%s, %s, 'BTC/USDT', 'long', 0.0001, 50000.0, NOW())
                    RETURNING id
                """, (user_id, strategy_id))
                row = cur.fetchone()
                if row:
                    probe_id = row['id']
                else:
                    logger.warning("INSERT did not return ID. Querying for it...")
                    cur.execute("SELECT id FROM qd_strategy_positions WHERE strategy_id=%s AND symbol='BTC/USDT'", (strategy_id,))
                    probe_id = cur.fetchone()['id']
                conn.commit()
                logger.info(f"Created probe position ID: {probe_id}")

            # Force reset the probe to a known mis-state: Side=Long, Size=0.042 
            # (assuming Exchange has something else, e.g. 0.008, or even if 0, it tests logic)
            # This ensures we test "Update" (if match) or "Delete" (if exchange is 0) correctly without side mismatch confusion.
            if probe_id:
                 cur.execute("UPDATE qd_strategy_positions SET side='long', size=0.042, updated_at=NOW() WHERE id=%s", (probe_id,))
                 conn.commit()
                 logger.info(f"Reset probe (ID: {probe_id}) to Side='long', Size=0.042 for testing.")

            # 4. Run Sync Logic
            logger.info("--- Running PendingOrderWorker._sync_positions_best_effort ---")
            worker = PendingOrderWorker()
            worker._sync_positions_best_effort()
            
            # 5. Check Result
            if probe_id:
                cur.execute("SELECT * FROM qd_strategy_positions WHERE id = %s", (probe_id,))
                after = cur.fetchone()
                
                real_btc_amt = real_positions_map.get("BTCUSDT", 0.0)
                
                if not after:
                    if abs(real_btc_amt) < 1e-6:
                         logger.info("SUCCESS: Probe position was DELETED (Exchange matches 0).")
                    else:
                         logger.warning(f"WARNING: Probe deleted but exchange has {real_btc_amt}? (Unless symbol mismatch)")
                else:
                    new_size = float(after['size'])
                    logger.info(f"RESULT: DB Position Size: {new_size}")
                    
                    if abs(new_size - abs(real_btc_amt)) < 1e-6:
                        logger.info(f"SUCCESS: DB synced to Exchange Size ({abs(real_btc_amt)}).")
                        ep = float(after.get('entry_price') or 0.0)
                        logger.info(f"RESULT: Entry Price in DB: {ep}")
                        if ep > 0:
                             logger.info("SUCCESS: Entry Price populated > 0")
                        else:
                             logger.warning("WARNING: Entry Price is 0 or missing!")
                    else:
                        logger.warning(f"MISMATCH: DB={new_size}, Exchange={real_btc_amt}. Sync might have skipped or failed?")

        except Exception as e:
            logger.error(f"Error occurred during test: {e}", exc_info=True)
            conn.rollback()
        finally:
            cur.close()

if __name__ == "__main__":
    test_real_sync_binance()
