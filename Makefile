up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

health:
	curl -s http://localhost:8000/health
	curl -s http://localhost:8001/health
	curl -s http://localhost:8002/health
	curl -s http://localhost:8003/health
