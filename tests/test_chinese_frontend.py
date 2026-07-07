from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings


def make_client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}"))
    return TestClient(app)


def test_home_page_is_chinese(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "小分子药物设计 Agent" in response.text
    assert "打开接口文档" in response.text
    assert "关系数据库" in response.text


def test_swagger_page_uses_chinese_title(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/docs")

    assert response.status_code == 200
    assert "小分子药物设计 Agent - 接口文档" in response.text


def test_openapi_metadata_is_chinese(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "小分子药物设计 Agent"
    assert schema["paths"]["/projects"]["post"]["summary"] == "创建项目"
    assert "内置靶点库" in {tag["name"] for tag in schema["tags"]}
