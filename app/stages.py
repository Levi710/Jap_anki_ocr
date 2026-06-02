from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

from .logging_utils import build_stage_logger
from .models import (
    ArtifactRecord,
    ConnectedComponentStats,
    LayoutCluster,
    LayoutClusterSet,
    PageFeature,
    PageFeatureSet,
    Profile,
    SectionTaxonomyEntry,
    StageManifest,
    StructureCandidate,
    StructureCandidateSet,
    StructureModel,
)
from .pdf_utils import PDFInspector
from .storage import RunDatabase


@dataclass(frozen=True)
class ProfilingRunContext:
    run_dir: Path
    pdf_path: Path
    fingerprint: dict[str, Any]
    created_at: datetime
    database: RunDatabase
    pdf_inspector: PDFInspector


@dataclass
class StageResult:
    artifacts: list[ArtifactRecord]
    metrics: dict[str, Any]
    outputs: dict[str, Any]
    parameters: dict[str, Any]


class Stage:
    name: str
    version: str

    def run(
        self,
        context: ProfilingRunContext,
        inputs: dict[str, Any],
        stage_dir: Path,
    ) -> StageResult:
        raise NotImplementedError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _bucket(value: float) -> str:
    if value < 0.33:
        return "low"
    if value < 0.66:
        return "medium"
    return "high"


def _variance(values: list[float]) -> float:
    if not values:
        return 0.0
    mean_value = fmean(values)
    return fmean([(value - mean_value) ** 2 for value in values])


class StageRunner:
    def __init__(self, context: ProfilingRunContext) -> None:
        self.context = context
        self.stages_root = context.run_dir / "stages"
        self.stages_root.mkdir(exist_ok=True)

    def run_stage(self, stage: Stage, inputs: dict[str, Any]) -> StageResult:
        stage_slug = stage.name.lower().replace(" ", "_")
        stage_dir = self.stages_root / stage_slug
        stage_dir.mkdir(parents=True, exist_ok=True)
        logger = build_stage_logger(stage.name, str(stage_dir / "log.jsonl"))
        started_at = _utc_now()
        logger.info("stage_start", extra={"event": "stage_start", "stage": stage.name})
        result = stage.run(self.context, inputs, stage_dir)
        completed_at = _utc_now()
        manifest = StageManifest(
            stage_name=stage.name,
            stage_version=stage.version,
            started_at_utc=started_at,
            completed_at_utc=completed_at,
            status="success",
            artifacts=result.artifacts,
            metrics=result.metrics,
            parameters=result.parameters,
        )
        _write_json(stage_dir / "manifest.json", manifest.model_dump(mode="json"))
        _write_json(stage_dir / "metrics.json", result.metrics)
        _write_json(stage_dir / "artifacts.json", [artifact.model_dump(mode="json") for artifact in result.artifacts])
        self.context.database.record_stage_metrics(stage.name, result.metrics)
        self.context.database.record_stage_artifacts(stage.name, result.artifacts)
        logger.info("stage_complete", extra={"event": "stage_complete", "stage": stage.name})
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        return result


class ProfilingSamplingStage(Stage):
    name = "ProfilingSampling"
    version = "2.0"

    def run(self, context: ProfilingRunContext, inputs: dict[str, Any], stage_dir: Path) -> StageResult:
        page_count = context.pdf_inspector.page_count()
        target_samples = min(page_count, 12)
        if target_samples <= 1:
            sampled_pages = [0]
        else:
            step = (page_count - 1) / (target_samples - 1)
            sampled_pages = sorted({int(round(step * idx)) for idx in range(target_samples)})
        sample_payload = {"page_count": page_count, "sampled_pages": sampled_pages}
        sample_path = context.run_dir / "sampled_pages.json"
        _write_json(sample_path, sample_payload)
        artifacts = [
            ArtifactRecord(
                name="sampled_pages",
                path=str(sample_path.relative_to(context.run_dir)),
                description="Sampled page indices for profiling",
                content_type="application/json",
            )
        ]
        metrics = {"page_count": page_count, "sample_count": len(sampled_pages)}
        return StageResult(artifacts=artifacts, metrics=metrics, outputs={"sampled_pages": sampled_pages}, parameters={})


class PageFeatureExtractionStage(Stage):
    name = "PageFeatureExtraction"
    version = "2.0"

    def run(self, context: ProfilingRunContext, inputs: dict[str, Any], stage_dir: Path) -> StageResult:
        features: list[PageFeature] = []
        for page in context.pdf_inspector.iter_pages():
            lines = [line.strip() for line in page.text.splitlines() if line.strip()]
            line_lengths = [len(line) for line in lines]
            line_count = len(lines)
            avg_line_length = fmean(line_lengths) if line_lengths else 0.0
            line_length_variance = _variance([float(value) for value in line_lengths])
            page_area = max(page.width * page.height, 1.0)
            text_density = min((len(page.text) / page_area) * 100.0, 1.0)
            whitespace_density = max(0.0, 1.0 - text_density)
            line_density = min(line_count / max(page.height / 12.0, 1.0), 1.0)
            space_runs = sum(1 for line in lines if "  " in line)
            column_hint_ratio = space_runs / max(line_count, 1)
            table_signal = min(column_hint_ratio + (1.0 - min(line_length_variance / 200.0, 1.0)) * 0.3, 1.0)
            image_coverage_ratio = min(page.image_count / 4.0, 1.0)
            connected_components = ConnectedComponentStats(
                component_count=line_count,
                avg_component_size=avg_line_length,
                size_variance=line_length_variance,
            )
            features.append(
                PageFeature(
                    page_index=page.index,
                    page_width=page.width,
                    page_height=page.height,
                    text_density=text_density,
                    whitespace_density=whitespace_density,
                    connected_components=connected_components,
                    line_density=line_density,
                    table_likeness=table_signal,
                    image_coverage_ratio=image_coverage_ratio,
                    line_count=line_count,
                    avg_line_length=avg_line_length,
                    line_length_variance=line_length_variance,
                )
            )
        feature_set = PageFeatureSet(page_count=len(features), features=features)
        output_path = context.run_dir / "page_features.json"
        _write_json(output_path, feature_set.model_dump(mode="json"))
        artifacts = [
            ArtifactRecord(
                name="page_features",
                path=str(output_path.relative_to(context.run_dir)),
                description="Computed page-level layout features",
                content_type="application/json",
            )
        ]
        metrics = {
            "page_count": len(features),
            "avg_text_density": fmean([feature.text_density for feature in features]) if features else 0.0,
            "avg_table_likeness": fmean([feature.table_likeness for feature in features]) if features else 0.0,
        }
        return StageResult(
            artifacts=artifacts,
            metrics=metrics,
            outputs={"page_features": features},
            parameters={},
        )


class LayoutClusteringStage(Stage):
    name = "LayoutClustering"
    version = "2.0"

    def run(self, context: ProfilingRunContext, inputs: dict[str, Any], stage_dir: Path) -> StageResult:
        features: Iterable[PageFeature] = inputs["page_features"]
        buckets: dict[tuple[str, ...], list[PageFeature]] = {}
        for feature in features:
            key = (
                _bucket(feature.text_density),
                _bucket(feature.whitespace_density),
                _bucket(feature.line_density),
                _bucket(feature.table_likeness),
                _bucket(feature.image_coverage_ratio),
            )
            buckets.setdefault(key, []).append(feature)
        clusters: list[LayoutCluster] = []
        for idx, (key, grouped) in enumerate(sorted(buckets.items(), key=lambda item: item[0])):
            centroid = {
                "text_density": fmean([feature.text_density for feature in grouped]),
                "whitespace_density": fmean([feature.whitespace_density for feature in grouped]),
                "line_density": fmean([feature.line_density for feature in grouped]),
                "table_likeness": fmean([feature.table_likeness for feature in grouped]),
                "image_coverage_ratio": fmean([feature.image_coverage_ratio for feature in grouped]),
            }
            def distance(feature: PageFeature) -> float:
                return (
                    abs(feature.text_density - centroid["text_density"])
                    + abs(feature.whitespace_density - centroid["whitespace_density"])
                    + abs(feature.line_density - centroid["line_density"])
                    + abs(feature.table_likeness - centroid["table_likeness"])
                    + abs(feature.image_coverage_ratio - centroid["image_coverage_ratio"])
                )
            representative = min(grouped, key=distance)
            explanation = (
                f"Cluster of {len(grouped)} pages with text density {key[0]}, "
                f"whitespace {key[1]}, line density {key[2]}, "
                f"table-likeness {key[3]}, image coverage {key[4]}."
            )
            clusters.append(
                LayoutCluster(
                    cluster_id=f"cluster_{idx + 1}",
                    page_indices=[feature.page_index for feature in grouped],
                    representative_page=representative.page_index,
                    centroid=centroid,
                    feature_bins={
                        "text_density": key[0],
                        "whitespace_density": key[1],
                        "line_density": key[2],
                        "table_likeness": key[3],
                        "image_coverage_ratio": key[4],
                    },
                    explanation=explanation,
                )
            )
        cluster_set = LayoutClusterSet(
            method="deterministic_bins_v1",
            cluster_count=len(clusters),
            clusters=clusters,
        )
        output_path = context.run_dir / "clusters.json"
        _write_json(output_path, cluster_set.model_dump(mode="json"))
        artifacts = [
            ArtifactRecord(
                name="layout_clusters",
                path=str(output_path.relative_to(context.run_dir)),
                description="Layout clusters derived from page features",
                content_type="application/json",
            )
        ]
        metrics = {"cluster_count": len(clusters), "largest_cluster_size": max((len(c.page_indices) for c in clusters), default=0)}
        return StageResult(
            artifacts=artifacts,
            metrics=metrics,
            outputs={"clusters": clusters},
            parameters={},
        )


class SectionDiscoveryStage(Stage):
    name = "SectionDiscovery"
    version = "2.0"

    def run(self, context: ProfilingRunContext, inputs: dict[str, Any], stage_dir: Path) -> StageResult:
        clusters: Iterable[LayoutCluster] = inputs["clusters"]
        sections: list[SectionTaxonomyEntry] = []
        for cluster in clusters:
            bins = cluster.feature_bins
            if bins["table_likeness"] == "high":
                label = "table_like"
            elif bins["image_coverage_ratio"] == "high":
                label = "image_heavy"
            elif bins["text_density"] == "high":
                label = "text_dense"
            else:
                label = "sparse"
            confidence = 0.6
            if bins["text_density"] == "high" or bins["table_likeness"] == "high":
                confidence = 0.75
            description = (
                f"Section derived from {cluster.cluster_id} with {label} characteristics "
                f"and representative page {cluster.representative_page}."
            )
            sections.append(
                SectionTaxonomyEntry(
                    section_id=f"section_{cluster.cluster_id}",
                    label=label,
                    cluster_id=cluster.cluster_id,
                    confidence=confidence,
                    description=description,
                )
            )
        output_path = context.run_dir / "section_taxonomy.json"
        _write_json(output_path, [section.model_dump(mode="json") for section in sections])
        artifacts = [
            ArtifactRecord(
                name="section_taxonomy",
                path=str(output_path.relative_to(context.run_dir)),
                description="Section taxonomy inferred from layout clusters",
                content_type="application/json",
            )
        ]
        metrics = {"section_count": len(sections)}
        return StageResult(
            artifacts=artifacts,
            metrics=metrics,
            outputs={"section_taxonomy": sections},
            parameters={},
        )


class StructureModelDiscoveryStage(Stage):
    name = "StructureModelDiscovery"
    version = "2.0"

    def _candidate_from_pages(
        self,
        candidate_type: str,
        pages: list[PageFeature],
        threshold_notes: dict[str, Any],
    ) -> StructureCandidate:
        page_indices = [feature.page_index for feature in pages]
        if pages:
            confidence = min(1.0, 0.4 + fmean([feature.table_likeness for feature in pages]) if candidate_type == "table_like" else 0.4 + fmean([feature.line_density for feature in pages]) if candidate_type == "list_like" else 0.4 + fmean([1.0 - min(feature.line_length_variance / 200.0, 1.0) for feature in pages]))
        else:
            confidence = 0.15
        explanation = (
            f"Detected {candidate_type} pattern across {len(page_indices)} pages using generic layout signals."
            if pages
            else f"No strong {candidate_type} signal detected; keeping low-confidence candidate."
        )
        evidence = {
            "page_indices": page_indices,
            "thresholds": threshold_notes,
        }
        return StructureCandidate(
            candidate_id=f"{candidate_type}_candidate",
            candidate_type=candidate_type,  # type: ignore[arg-type]
            pages=page_indices,
            confidence=confidence,
            explanation=explanation,
            evidence=evidence,
        )

    def run(self, context: ProfilingRunContext, inputs: dict[str, Any], stage_dir: Path) -> StageResult:
        features: list[PageFeature] = inputs["page_features"]
        table_pages = [feature for feature in features if feature.table_likeness >= 0.6]
        list_pages = [
            feature
            for feature in features
            if feature.line_density >= 0.6 and feature.avg_line_length <= 40
        ]
        repeated_pages = [
            feature
            for feature in features
            if feature.line_length_variance <= 120 and feature.line_count >= 5
        ]
        candidates = [
            self._candidate_from_pages(
                "table_like",
                table_pages,
                {"table_likeness_min": 0.6},
            ),
            self._candidate_from_pages(
                "list_like",
                list_pages,
                {"line_density_min": 0.6, "avg_line_length_max": 40},
            ),
            self._candidate_from_pages(
                "repeated_rows",
                repeated_pages,
                {"line_length_variance_max": 120, "line_count_min": 5},
            ),
        ]
        candidate_set = StructureCandidateSet(candidates=candidates, generated_at_utc=_utc_now())
        output_path = context.run_dir / "structure_candidates.json"
        _write_json(output_path, candidate_set.model_dump(mode="json"))
        artifacts = [
            ArtifactRecord(
                name="structure_candidates",
                path=str(output_path.relative_to(context.run_dir)),
                description="Structure candidates inferred from page features",
                content_type="application/json",
            )
        ]
        models: list[StructureModel] = []
        for candidate in candidates:
            models.append(
                StructureModel(
                    model_id=f"model_{candidate.candidate_type}",
                    candidate_id=candidate.candidate_id,
                    model_type=candidate.candidate_type,
                    rules=[{"type": candidate.candidate_type, "thresholds": candidate.evidence.get("thresholds")}],
                    confidence=candidate.confidence,
                )
            )
        models_path = context.run_dir / "structure_models.json"
        _write_json(models_path, [model.model_dump(mode="json") for model in models])
        artifacts.append(
            ArtifactRecord(
                name="structure_models",
                path=str(models_path.relative_to(context.run_dir)),
                description="Structure models derived from candidates",
                content_type="application/json",
            )
        )
        metrics = {
            "candidate_count": len(candidates),
            "table_like_pages": len(table_pages),
            "list_like_pages": len(list_pages),
            "repeated_row_pages": len(repeated_pages),
        }
        return StageResult(
            artifacts=artifacts,
            metrics=metrics,
            outputs={"structure_candidates": candidates, "structure_models": models},
            parameters={},
        )


class RuleSynthesisAndRankingStage(Stage):
    name = "RuleSynthesisAndRanking"
    version = "2.0"

    def run(self, context: ProfilingRunContext, inputs: dict[str, Any], stage_dir: Path) -> StageResult:
        clusters: list[LayoutCluster] = inputs["clusters"]
        sections: list[SectionTaxonomyEntry] = inputs["section_taxonomy"]
        structure_models: list[StructureModel] = inputs["structure_models"]
        candidate_map = {model.model_type: model for model in structure_models}
        table_conf = candidate_map.get("table_like").confidence if candidate_map.get("table_like") else 0.0
        list_conf = candidate_map.get("list_like").confidence if candidate_map.get("list_like") else 0.0
        repeat_conf = candidate_map.get("repeated_rows").confidence if candidate_map.get("repeated_rows") else 0.0
        rules = [model.rules[0] for model in structure_models if model.rules]
        layout_profile = {
            "cluster_count": len(clusters),
            "representative_pages": [cluster.representative_page for cluster in clusters],
        }
        profiles: list[Profile] = []
        profiles.append(
            Profile(
                name="profile_A",
                layout_profile=layout_profile,
                section_taxonomy=sections,
                structure_models=structure_models,
                detection_rules=rules,
                confidence_explanation="Optimized for table-like structures with supportive repeated rows.",
                ranking_score=0.6 * table_conf + 0.2 * repeat_conf + 0.2 * list_conf,
                strengths=["Table structure emphasis", "Consistent row detection"],
                weaknesses=["May underweight list-like layouts"],
            )
        )
        profiles.append(
            Profile(
                name="profile_B",
                layout_profile=layout_profile,
                section_taxonomy=sections,
                structure_models=structure_models,
                detection_rules=rules,
                confidence_explanation="Optimized for list-like layouts with balanced table awareness.",
                ranking_score=0.6 * list_conf + 0.2 * table_conf + 0.2 * repeat_conf,
                strengths=["List layout emphasis", "Broad coverage"],
                weaknesses=["Lower sensitivity to dense tables"],
            )
        )
        profiles.append(
            Profile(
                name="profile_C",
                layout_profile=layout_profile,
                section_taxonomy=sections,
                structure_models=structure_models,
                detection_rules=rules,
                confidence_explanation="Balanced profile across detected structure candidates.",
                ranking_score=(table_conf + list_conf + repeat_conf) / 3.0,
                strengths=["Balanced layout coverage"],
                weaknesses=["Less specialized for any single structure type"],
            )
        )
        profiles_sorted = sorted(profiles, key=lambda profile: profile.ranking_score, reverse=True)
        report_path = context.run_dir / "profile_report.md"
        report_lines = ["# Profile Ranking", ""]
        for idx, profile in enumerate(profiles_sorted, start=1):
            report_lines.append(f"{idx}. {profile.name} (score: {profile.ranking_score:.2f})")
        report_lines.append("")
        recommended = profiles_sorted[0]
        report_lines.append(f"## Recommended Profile\n\n{recommended.name}")
        report_lines.append("\n## Strengths")
        for strength in recommended.strengths:
            report_lines.append(f"- {strength}")
        report_lines.append("\n## Weaknesses")
        for weakness in recommended.weaknesses:
            report_lines.append(f"- {weakness}")
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        artifacts: list[ArtifactRecord] = [
            ArtifactRecord(
                name="profile_report",
                path=str(report_path.relative_to(context.run_dir)),
                description="Markdown report ranking synthesized profiles",
                content_type="text/markdown",
            )
        ]
        for profile in profiles:
            profile_path = context.run_dir / f"{profile.name}.json"
            _write_json(profile_path, profile.model_dump(mode="json"))
            artifacts.append(
                ArtifactRecord(
                    name=profile.name,
                    path=str(profile_path.relative_to(context.run_dir)),
                    description=f"Synthesized {profile.name} output",
                    content_type="application/json",
                )
            )
        metrics = {"profile_count": len(profiles), "recommended_profile": recommended.name}
        return StageResult(
            artifacts=artifacts,
            metrics=metrics,
            outputs={"profiles": profiles_sorted, "recommended_profile": recommended.name},
            parameters={},
        )
