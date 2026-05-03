from pydantic import BaseModel


class SearchResultResponse(BaseModel):
    kind: str
    id: int
    title: str
    subtitle: str
    route_path: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultResponse]
