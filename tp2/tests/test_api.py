from fastapi.testclient import TestClient

from src.main import app


client = TestClient(app)


def test_create_and_get_mock_task():
    response = client.post(
        "/tareas",
        json={"tipo": "esperar", "parametros": {"segundos": 2}},
    )

    assert response.status_code == 202
    task = response.json()
    assert task["estado"] == "pendiente"
    assert task["tipo"] == "esperar"

    detail_response = client.get(f"/tareas/{task['id']}")

    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == task["id"]


def test_list_filter_delete_and_statistics_mock_tasks():
    create_response = client.post(
        "/tareas",
        json={"tipo": "hashear", "parametros": {"texto": "hola"}},
    )
    task_id = create_response.json()["id"]

    list_response = client.get("/tareas", params={"estado": "pendiente"})
    assert list_response.status_code == 200
    assert any(task["id"] == task_id for task in list_response.json())

    delete_response = client.delete(f"/tareas/{task_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["estado"] == "cancelada"

    statistics_response = client.get("/estadisticas")
    assert statistics_response.status_code == 200
    assert "totales_por_estado" in statistics_response.json()