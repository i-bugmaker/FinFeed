"""共享周期轮询原语。

架构评估 §8 对 12 处 `while True` 的甄别结论（2026-09-04）：

  * 真全局周期轮询（收敛到本模块）—— content_fetch.content_backfill_loop
  * 连接生命周期轮询（SSE/WS 每连接一环，保留原位，勿强行收敛）——
    capital_dashboard/ws.py、market/ws_feed.py、ui/.../realtime.py、
    stock_monitor/router.py：其循环随连接生灭，收敛进全局调度器反而
    制造生命周期错配
  * 非调度器（批处理分页 / 队列排空 / WS 收包 / 键盘监听 / 子串扫描）——
    analysis/crossref.py、analysis/sentiment.py、screener/datasource.py、
    ui/.../shared.py、cli.py 等，属正常控制流，不处理

原语统一解决三个历史问题：异常静默吞掉、取消不退出、慢任务导致间隔漂移。
"""
