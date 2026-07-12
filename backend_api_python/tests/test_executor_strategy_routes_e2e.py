from app.utils.auth import generate_token


class _FakeStrategyService:
    def __init__(self):
        self.rows = {}
        self.next_id = 1000

    def create_strategy(self, payload):
        strategy_id = self.next_id
        self.next_id += 1
        row = dict(payload)
        row["id"] = strategy_id
        row["status"] = row.get("status") or "stopped"
        self.rows[strategy_id] = row
        return strategy_id

    def get_strategy(self, strategy_id, user_id=None):
        row = self.rows.get(int(strategy_id))
        if not row:
            return None
        if user_id is not None and int(row.get("user_id") or 0) != int(user_id):
            return None
        return dict(row)

    def get_strategy_type(self, strategy_id):
        row = self.rows.get(int(strategy_id)) or {}
        return row.get("strategy_type")

    def update_strategy_status(self, strategy_id, status, user_id=None):
        row = self.rows.get(int(strategy_id))
        if not row:
            return False
        if user_id is not None and int(row.get("user_id") or 0) != int(user_id):
            return False
        row["status"] = status
        return True


class _FakeTradingExecutor:
    def __init__(self):
        self.started = []

    def start_strategy(self, strategy_id):
        self.started.append(int(strategy_id))
        return True

    def wait_strategy_running(self, strategy_id, timeout=3.0):
        return True, ""


def _auth_headers(monkeypatch):
    from app.utils import auth as auth_module

    monkeypatch.setattr(auth_module, "_verify_token_version", lambda user_id, token_version: True)
    token = generate_token(7, "executor-test", "user", token_version=1)
    return {"Authorization": f"Bearer {token}"}


def test_executor_strategy_create_and_start_routes(client, monkeypatch):
    from app.routes import strategy as strategy_routes
    from app.routes import strategy_executor_routes

    service = _FakeStrategyService()
    executor = _FakeTradingExecutor()

    monkeypatch.setattr(strategy_executor_routes, "get_strategy_service", lambda: service)
    monkeypatch.setattr(strategy_routes, "get_strategy_service", lambda: service)
    monkeypatch.setattr(strategy_routes, "get_trading_executor", lambda: executor)
    monkeypatch.setattr(strategy_routes, "_find_live_strategy_conflict", lambda strategy, user_id: None)

    headers = _auth_headers(monkeypatch)
    created_ids = []
    for executor_type in ("grid", "dca", "martingale", "layered_martingale"):
        response = client.post(
            "/api/strategies/executors/create",
            headers=headers,
            json={
                "executor_type": executor_type,
                "strategy_name": f"E2E {executor_type}",
                "symbol": "BTC/USDT",
                "execution_mode": "signal",
                "start_price": 98000,
                "end_price": 102000,
                "grid_count": 6,
                "total_amount_quote": 600,
                "entry_price": 100000,
                "base_order_size": 100,
                "safety_order_size": 120,
                "price_deviation_pct": 0.01,
                "volume_multiplier": 1.5,
                "max_layers": 4,
                "layer_count": 5,
                "orders_per_layer": 3,
                "intra_spacing_1_pct": 0.005,
                "intra_spacing_2_pct": 0.008,
                "inter_spacing_1_pct": 0.012,
                "inter_spacing_2_pct": 0.015,
                "inter_spacing_3_pct": 0.018,
                "inter_spacing_4_pct": 0.022,
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["code"] == 1
        strategy_id = int(body["data"]["id"])
        created_ids.append(strategy_id)
        row = service.rows[strategy_id]
        trading_config = row["trading_config"]
        assert row["strategy_type"] == "ScriptStrategy"
        assert row["strategy_mode"] == "bot"
        assert trading_config["strategy_family"] == "executor"
        assert trading_config["executor_type"] == executor_type
        assert trading_config["bot_type"] == executor_type
        assert row["strategy_code"]

    for strategy_id in created_ids:
        response = client.post(
            f"/api/strategies/start?id={strategy_id}",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.get_json()["code"] == 1
        assert service.rows[strategy_id]["status"] == "running"

    assert executor.started == created_ids
