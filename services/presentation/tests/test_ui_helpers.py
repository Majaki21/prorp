from services.presentation.app.view_helpers import display_plan_name, completion_percent, format_money


def test_display_plan_name_preserves_plan_code_and_context():
    assert display_plan_name({"nazwa_dokumentu": "Plan ORP — działania Policji"}) == "Plan ORP — działania Policji"
    assert display_plan_name({"nazwa_dokumentu": "Plan P — bezpieczeństwo i porządek publiczny"}) == "Plan P — bezpieczeństwo i porządek publiczny"


def test_completion_percent_returns_average_as_percentage():
    assert completion_percent([{"poziom_realizacji": 0.25}, {"poziom_realizacji": 0.75}]) == 50
    assert completion_percent([]) is None


def test_format_money_is_readable():
    assert format_money(1234567) == "1 234 567 zł"
