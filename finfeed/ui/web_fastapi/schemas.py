"""Web API 响应契约（pydantic）。

架构评估 §7：137 个端点此前 response_model 仅 5 处且全为 None，前端 TS
覆盖率 0%，后端改字段名前端静默炸在运行时。本模块为首批（新闻核心链路）
端点补齐 OpenAPI 契约。

说明：这些端点直接返回 JSONResponse（跳过 FastAPI 序列化），response_model
仅用于 OpenAPI 文档与类型生成（openapi-typescript），不影响运行时行为——
因此模型必须与实际返回**逐字段对齐**，修改时需同步 shared.py 的构造逻辑。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class NewsItemOut(BaseModel):
    """单条新闻（storage.models.NewsItem.to_dict 的镜像）。"""

    id: int
    title: str
    url: str
    source: str
    publish_time: str = ""
    publish_ts: int = 0
    intro: str = ""
    content: str = ""          # 列表接口不携带，详情接口携带
    category: str = ""
    sentiment: str = ""
    importance: float = 0.0
    keywords: List[str] = []
    stocks: List[str] = []
    is_read: bool = False
    is_favorite: bool = False
    duplicate_count: int = 0
    duplicate_sources: List[str] = []
    meta: Dict[str, Any] = {}


class NewsListOut(BaseModel):
    """flash / articles / sentiment / favorites 列表信封（shared._build_news_response 镜像）。"""

    news: List[NewsItemOut]
    total: int
    offset: int
    next_offset: Optional[int] = None
    limit: int
    returned_count: int
    has_more: bool
    stats: Dict[str, Any] = {}
    sources: List[str] = []
    server_ts: float = 0.0


class ErrorOut(BaseModel):
    error: str


class StockNamesOut(BaseModel):
    stock_names: Dict[str, str] = {}
    error: Optional[str] = None


class DateRangeOut(BaseModel):
    min: str = ""
    max: str = ""
    dates: List[str] = []


class SearchOut(BaseModel):
    keyword: str
    count: int
    news: List[NewsItemOut]


class ArticleMetaOut(BaseModel):
    """详情接口的结构化正文元数据（content_extractor 产物）。"""

    text: str = ""
    author: Optional[str] = None
    publish_time: Optional[str] = None
    images: List[str] = []


class NewsDetailOut(BaseModel):
    success: bool
    news: Optional[NewsItemOut] = None
    article: Optional[ArticleMetaOut] = None
    error: Optional[str] = None


class MutationOut(BaseModel):
    """收藏/已读等轻量写操作回执。"""

    success: bool
    error: Optional[str] = None
    is_favorite: Optional[bool] = None
