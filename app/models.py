from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ArtifactRecord(BaseModel):
    name: str
    path: str
    description: str
    content_type: str


class StageManifest(BaseModel):
    stage_name: str
    stage_version: str
    started_at_utc: datetime
    completed_at_utc: datetime
    status: Literal["success", "failure"]
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ConnectedComponentStats(BaseModel):
    component_count: int
    avg_component_size: float
    size_variance: float


class PageFeature(BaseModel):
    page_index: int
    page_width: float
    page_height: float
    text_density: float
    whitespace_density: float
    connected_components: ConnectedComponentStats
    line_density: float
    table_likeness: float
    image_coverage_ratio: float
    line_count: int
    avg_line_length: float
    line_length_variance: float


class PageFeatureSet(BaseModel):
    page_count: int
    features: list[PageFeature]


class LayoutCluster(BaseModel):
    cluster_id: str
    page_indices: list[int]
    representative_page: int
    centroid: dict[str, float]
    feature_bins: dict[str, str]
    explanation: str


class LayoutClusterSet(BaseModel):
    method: str
    cluster_count: int
    clusters: list[LayoutCluster]


class SectionTaxonomyEntry(BaseModel):
    section_id: str
    label: str
    cluster_id: str
    confidence: float
    description: str


class StructureCandidate(BaseModel):
    candidate_id: str
    candidate_type: Literal["table_like", "list_like", "repeated_rows"]
    pages: list[int]
    confidence: float
    explanation: str
    evidence: dict[str, Any]


class StructureCandidateSet(BaseModel):
    candidates: list[StructureCandidate]
    generated_at_utc: datetime


class StructureModel(BaseModel):
    model_id: str
    candidate_id: str
    model_type: str
    rules: list[dict[str, Any]]
    confidence: float


class Profile(BaseModel):
    name: str
    layout_profile: dict[str, Any]
    section_taxonomy: list[SectionTaxonomyEntry]
    structure_models: list[StructureModel]
    detection_rules: list[dict[str, Any]]
    confidence_explanation: str
    ranking_score: float
    strengths: list[str]
    weaknesses: list[str]
