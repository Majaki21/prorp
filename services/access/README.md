# Access Service (PoC)

All externally consumed PRO RP data APIs should be called through this service. The data service is an internal service and must not be exposed directly to clients.

## Identity for the demo

- `X-Person-Id: demo-U-PRM` selects a seeded demo identity.
- If `DEFAULT_PERSON_ID` is configured, requests without the header use that demo identity.
- This is a PoC identity selector, **not authentication**. A production deployment must derive identity from a trusted IdP/session and clients must not be allowed to choose arbitrary person IDs.

## Read endpoints

- `GET /me` — current demo identity.
- `GET /units` and `GET /units/{unit_id}` — units within the person's organizational scope. `region_id` and `plan_id` are optional filters on the collection endpoint.
- `GET /plans` and `GET /plans/{plan_id}` — plans within organizational scope and permitted classification.
- `GET /tasks` — filtered task list. Optional filters: `plan_id`, `unit_id`, `region_id`, `limit`.
- `GET /tasks/{plan_id}/{task_id}` — task details, with only visible unit references and a safe plan summary.
- `GET /state` — filtered operational snapshot used by simulation.
- `GET /health` — service health.

Unknown classifications fail closed. Both a task's own classification and its plan's classification are checked. Inaccessible detail records return `404` to avoid disclosing whether a record exists. Unit visibility follows the hierarchy downward; existing direct cooperation relations may add the peer unit and its descendants. Cooperation is not transitive.

The current data model does not contain a separate report entity or report-detail endpoint. Real-time progress fields are returned as part of task details. If dedicated reports are added later, they must use the same policy helpers before being exposed.

## Examples

```bash
curl -H 'X-Person-Id: demo-U-PRM' http://localhost:8002/me
curl -H 'X-Person-Id: demo-U-PRM' http://localhost:8002/plans
curl -H 'X-Person-Id: demo-U-PRM' http://localhost:8002/plans/O
curl -H 'X-Person-Id: demo-U-PRM' http://localhost:8002/tasks
curl -H 'X-Person-Id: demo-U-PRM' http://localhost:8002/tasks/O/1
curl -H 'X-Person-Id: demo-U-PRM' http://localhost:8002/units
curl -H 'X-Person-Id: demo-U-PRM' http://localhost:8002/state
```

Use `/docs` on the access service for the interactive OpenAPI specification. Do not call the internal data service from external clients.
