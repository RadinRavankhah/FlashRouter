async def get_usage_analytics(self, limit=50, offset=0, model_id=None, gateway_key_id=None):
    conn = await self._db.connection
    sql = "SELECT * FROM usage_records WHERE 1=1"
    params = []
    if model_id: sql += " AND request_id IN (SELECT request_id FROM requests WHERE model_id=?)"; params.append(model_id)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    return await conn.execute_fetchall(sql, params)
