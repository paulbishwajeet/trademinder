def test_models_importable():
    from app.models.trade import Trade
    from app.models.rationale import Rationale
    from app.models.commentary import Commentary
    from app.models.alert import Alert
    from app.models.briefing import DailyBriefing
    assert Trade.__tablename__ == "trades"
    assert Rationale.__tablename__ == "rationale"
    assert Commentary.__tablename__ == "commentary"
    assert Alert.__tablename__ == "alerts"
    assert DailyBriefing.__tablename__ == "daily_briefings"
