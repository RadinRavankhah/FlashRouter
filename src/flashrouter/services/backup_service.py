def backup(data_dir): return {"status":"backed_up","path":"%s/backup.db" % data_dir}
def restore(data_dir, backup_path): return {"status":"restored"}
