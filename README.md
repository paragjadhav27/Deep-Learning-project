# FaceLens

Privacy-first web app with three **illustrative, opt-in** face-image tools: age estimation, perceived-presentation estimation, and age-transformation previews. None of them is suitable for identification or any consequential decision.

- Product and technical plan: [docs/PLAN.md](docs/PLAN.md)
- API service: [apps/api](apps/api/README.md)
- Web app: [apps/web](apps/web/README.md)

**Status:** Phase 3 complete (API, face pipeline, production backends, web app). Face detection is real (YuNet, MIT). The three estimators are still **mocks**, labeled as such in the API and with a banner in the UI; see [docs/MODEL_CARDS.md](docs/MODEL_CARDS.md).

```bash
docker compose up --build        # http://localhost:3000 (web, API, worker, Postgres, Redis, SeaweedFS)
```

Operations: [docs/RUNBOOK.md](docs/RUNBOOK.md)
