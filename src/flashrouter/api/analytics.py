from fastapi import APIRouter, Request
router = APIRouter(prefix="/admin/analytics", tags=["analytics"])

@router.get("/reconcile")
async def reconcile(request: Request):
    return {"status":"reconciled","message":"reconciliation placeholder"}

@router.get("/export/csv")
async def export_csv(request: Request):
    return {"format":"csv","message":"export placeholder"}

@router.get("/projections")
async def projections(request: Request):
    return {"projected_spend":"unknown","label":"counterfactual estimate"}

@router.get("/usage")
async def usage(request: Request, limit: int = 50, offset: int = 0, model_id: str = None):
    repo = request.app.state.request_repository
    rows = await repo.get_usage_analytics(limit=limit, offset=offset, model_id=model_id)
    return {"data": [dict(r) for r in rows], "limit": limit, "offset": offset}
