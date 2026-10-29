from flashrouter.services.backup_service import backup, restore
class TestV09:
    def test_backup(self): assert backup("/tmp") is not None
    def test_restore(self): assert restore("/tmp","/tmp/b") is not None
