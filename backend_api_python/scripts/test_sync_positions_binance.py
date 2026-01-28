
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

def test_oversized_close_correction():
    """
    Test that if a Close signal asks for more than we hold, it clamps to held amount.
    Uses REAL WORKER and DB (Integration Test).
    Pre-condition: Exchange position is 0 (or known).
    """
    logger.info(">>> Starting Oversized Close Correction Test (REAL INTEGRATION)")
    
    from app.services.pending_order_worker import PendingOrderWorker
    
    # 1. Find Strategy
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM qd_strategies_trading WHERE execution_mode='live' LIMIT 1")
        row = cur.fetchone()
        cur.close()
        
    if not row:
        logger.warning("Skipping oversized test: No live strategy found.")
        return

    strategy_id = row['id']
    logger.info(f"Using Strategy ID {strategy_id} for test.")

    # 2. Setup DB Position: Ensure we have exactly 0.01 BTC (Ghost)
    # Since sync runs before execution, this ghost position SHOULD be deleted if Exchange matches 0.
    # Therefore, the Order Amount of 1.0 should become 0.0.
    test_sym = "BTC/USDT"
    target_pos_size = 0.01
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        # Find existing or insert
        cur.execute(
            "SELECT id FROM qd_strategy_positions WHERE strategy_id=%s AND symbol=%s AND side='long'", 
            (strategy_id, test_sym)
        )
        pos_row = cur.fetchone()
        if not pos_row:
             cur.execute(
                 "INSERT INTO qd_strategy_positions (user_id, strategy_id, symbol, side, size, entry_price, updated_at) VALUES (1, %s, %s, 'long', %s, 50000, NOW()) RETURNING id",
                 (strategy_id, test_sym, target_pos_size)
             )
        else:
             cur.execute("UPDATE qd_strategy_positions SET size=%s, side='long', updated_at=NOW() WHERE id=%s", (target_pos_size, pos_row['id']))
        conn.commit()
        cur.close()

    # 3. Instantiate Worker
    worker = PendingOrderWorker()
    
    # 4. Trigger _execute_live_order with amount=1.0 (100x holding)
    payload = {
        "strategy_id": strategy_id,
        "symbol": "BTCUSDT",
        "signal_type": "close_long",
        "amount": 1.0, 
        "price": 60000,
        "market_type": "swap"
    }
    order_row = {"id": 99999, "strategy_id": strategy_id, "amount": 1.0, "price": 60000, "symbol": "BTCUSDT"}
    
    logger.info("Triggering execution with amount=1.0 (Held Ghost=0.01, Exchange=0.0)...")
    logger.info("EXPECTATION: Sync deletes Ghost -> Held becomes 0 -> Amount corrects to 0 -> Order blocked/skipped.")
    
    try:
        # We catch exceptions because create_client might fail or create_order might fail if amount is 0
        worker._execute_live_order(order_id=99999, order_row=order_row, payload=payload)
        logger.info("[TEST END] Execution finished. Check logs above for '[RiskControl]' or '[Sync]' messages.")
    except Exception as e:
        logger.error(f"[TEST END] Execution raised exception (Expected if amount=0?): {e}")

if __name__ == "__main__":
    test_real_sync_binance()
    print("-" * 60)
    test_oversized_close_correction()
