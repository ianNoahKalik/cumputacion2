import time

from fastapi.testclient import TestClient

from src.main import _tareas, app


def _wait_for_state(client: TestClient, task_id: str, state: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        task = client.get(f"/tareas/{task_id}").json()
        if task["estado"] == state:
            return task
        time.sleep(0.01)
    raise AssertionError(f"La tarea {task_id} no alcanzo el estado {state}")


def test_statistics_reports_totals_average_and_busy_workers():
    _tareas.clear()
    with TestClient(app) as client:
        completed_response = client.post(
            "/tareas",
            json={"tipo": "esperar", "parametros": {"segundos": 0.03}},
        )
        failed_response = client.post(
            "/tareas",
            json={"tipo": "esperar", "parametros": {"segundos": -1}},
        )
        running_response = client.post(
            "/tareas",
            json={"tipo": "esperar", "parametros": {"segundos": 0.3}},
        )

        completed_id = completed_response.json()["id"]
        failed_id = failed_response.json()["id"]
        running_id = running_response.json()["id"]

        completed = _wait_for_state(client, completed_id, "completada")
        _wait_for_state(client, failed_id, "fallida")
        _wait_for_state(client, running_id, "ejecutando")

        statistics = client.get("/estadisticas")
        assert statistics.status_code == 200
        body = statistics.json()
        assert set(body["totales_por_estado"]) == {
            "pendiente",
            "ejecutando",
            "completada",
            "fallida",
            "cancelada",
        }
        assert body["totales_por_estado"]["completada"] == 1
        assert body["totales_por_estado"]["fallida"] == 1
        assert body["totales_por_estado"]["ejecutando"] == 1
        assert body["workers_ocupados"] == 1
        assert body["tiempo_promedio_segundos"] >= 0
        assert completed["iniciada_en"] is not None
        assert completed["finalizada_en"] is not None

        cancel_response = client.delete(f"/tareas/{running_id}")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["estado"] == "cancelada"

    _tareas.clear()


def test_statistics_counts_cancelled_tasks_and_completed_filter():
    _tareas.clear()
    with TestClient(app) as client:
        response = client.post(
            "/tareas",
            json={"tipo": "esperar", "parametros": {"segundos": 1}},
        )
        task_id = response.json()["id"]

        _wait_for_state(client, task_id, "ejecutando")
        assert client.delete(f"/tareas/{task_id}").json()["estado"] == "cancelada"

        statistics = client.get("/estadisticas").json()
        assert statistics["totales_por_estado"]["cancelada"] == 1
        assert statistics["workers_ocupados"] == 0
        assert statistics["tiempo_promedio_segundos"] >= 0

    _tareas.clear()
