"""house-hunter 数据采集层。

每个 source 模块对外暴露统一的高层 API（不暴露 raw HTTP 细节），
失败时返回 None 或空列表，由调用方做降级。
"""
