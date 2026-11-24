"""Small Windows headless port adjustments applied to private build copies."""
def adapt(filename, source):
    if filename=='filegen.c':
        marker=' return fseek(stream, offset, whence);'
        assert source.count(marker)==1
        return source.replace(marker, ' return _fseeki64(stream, offset, whence);')
    if filename=='phrecn.c':
        marker='    switch(ind_stop)\n    {'
        assert source.count(marker)==1
        return source.replace(marker, '''    if(ind_stop==PSTATUS_ENOSPC || ind_stop==PSTATUS_EACCES) {
      log_critical("RecoverX: unable to write candidate output (status %d)\\n", (int)ind_stop);
      log_flush();
      exit(74);
    }
'''+marker)
    return source
