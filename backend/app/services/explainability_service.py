"""
Explainable AI Framework (SHAP-based)
──────────────────────────────────────
Component 5: SHAP-based interpretability for interview scoring

Architecture:
  ┌──────────────────┐
  │ Evaluation Scores │
  └────────┬─────────┘
           │
  ┌────────▼─────────┐
  │ SHAP Explainer    │──▶ Feature attributions per dimension
  └────────┬─────────┘
           │
  ┌────────▼─────────┐
  │ Explanation       │──▶ Human-readable breakdown
  │ Generator         │    + improvement suggestions
  └────────┬─────────┘
           │
  ┌────────▼─────────┐
  │ Visualization     │──▶ Waterfall, bar, force plots (data)
  └──────────────────┘

Scoring Dimensions:
  1. Communication (structure, clarity, vocabulary)
  2. Technical Depth (accuracy, specificity, examples)
  3. Confidence (voice, face, response quality)
  4. Emotional Regulation (stability, stress management)
  5. Problem Solving (approach, reasoning, creativity)
"""

import json
import math
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

import numpy as np

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False

try:
    from sklearn.ensemble import GradientBoostingRegressor
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


class ExplainabilityService:
    """SHAP-based explainability framework for interview scoring."""

    # Feature names used across the scoring model
    FEATURE_NAMES = [
        "content_accuracy",
        "keyword_coverage",
        "response_depth",
        "response_length",
        "vocabulary_richness",
        "structural_clarity",
        "filler_word_ratio",
        "speaking_rate",
        "confidence_vocal",
        "confidence_facial",
        "emotion_stability",
        "stress_level",
        "eye_contact",
        "example_count",
        "specificity_score",
    ]

    DIMENSION_NAMES = [
        "Communication",
        "Technical Depth",
        "Confidence",
        "Emotional Regulation",
        "Problem Solving",
    ]

    def __init__(self):
        self._scoring_model = None
        self._explainer = None
        self._is_fitted = False

    def _build_scoring_model(self):
        """Build the scoring model used for SHAP explanations."""
        if not SKLEARN_AVAILABLE:
            return None

        model = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
        )
        return model

    def fit_model(self, training_data: Optional[np.ndarray] = None, scores: Optional[np.ndarray] = None):
        """Fit the scoring model for SHAP explanations.

        If no training data provided, uses synthetic data to bootstrap.
        """
        if not SKLEARN_AVAILABLE:
            return

        model = self._build_scoring_model()

        if training_data is None or scores is None:
            # Generate synthetic training data
            n_samples = 500
            training_data = np.random.rand(n_samples, len(self.FEATURE_NAMES))
            # Synthetic scoring function
            scores = (
                training_data[:, 0] * 0.25 +  # content_accuracy
                training_data[:, 1] * 0.15 +  # keyword_coverage
                training_data[:, 2] * 0.15 +  # response_depth
                training_data[:, 7] * 0.10 +  # speaking_rate normalized
                training_data[:, 8] * 0.10 +  # confidence_vocal
                training_data[:, 10] * 0.10 + # emotion_stability
                training_data[:, 13] * 0.10 + # example_count
                training_data[:, 14] * 0.05   # specificity_score
            ) * 100

            # Add noise
            scores += np.random.normal(0, 5, n_samples)
            scores = np.clip(scores, 0, 100)

        model.fit(training_data, scores)
        self._scoring_model = model
        self._is_fitted = True

        # Build SHAP explainer
        if SHAP_AVAILABLE:
            self._explainer = shap.TreeExplainer(model)

    def _ensure_fitted(self):
        if not self._is_fitted:
            self.fit_model()

    # ── Feature Extraction from Evaluation ────────────

    def extract_features(self, evaluation: Dict[str, Any]) -> np.ndarray:
        """Extract feature vector from an evaluation result."""
        features = np.zeros(len(self.FEATURE_NAMES))

        # Content accuracy (from similarity score)
        features[0] = evaluation.get("similarity_score", evaluation.get("content_score", 50)) / 100

        # Keyword coverage
        features[1] = evaluation.get("keyword_coverage", evaluation.get("keyword_score", 50)) / 100

        # Response depth
        features[2] = evaluation.get("depth_score", 50) / 100

        # Response length (normalized)
        answer = evaluation.get("answer_text", "")
        word_count = len(answer.split()) if isinstance(answer, str) else 50
        features[3] = min(1.0, word_count / 200)

        # Vocabulary richness
        if isinstance(answer, str) and answer:
            words = answer.lower().split()
            unique = len(set(words))
            features[4] = unique / max(len(words), 1)
        else:
            features[4] = 0.5

        # Structural clarity (from communication score)
        features[5] = evaluation.get("communication_score", 50) / 100

        # Filler word ratio (inverse of fluency)
        features[6] = 1 - evaluation.get("fluency_score", 50) / 100 if "fluency_score" in evaluation else 0.1

        # Speaking rate (normalized: 120 wpm = 0.5, optimal range 100-150)
        wpm = evaluation.get("words_per_minute", 120)
        features[7] = min(1.0, max(0.0, (wpm - 60) / 180))

        # Confidence (vocal + facial)
        features[8] = evaluation.get("confidence_score", 50) / 100
        features[9] = evaluation.get("facial_confidence", 50) / 100

        # Emotion stability
        features[10] = evaluation.get("emotion_stability", 50) / 100

        # Stress level (inverse)
        features[11] = 1 - evaluation.get("stress_level", 50) / 100

        # Eye contact
        features[12] = evaluation.get("eye_contact", 50) / 100

        # Example count (heuristic from text)
        if isinstance(answer, str):
            example_markers = ["for example", "such as", "for instance", "like when", "specifically"]
            features[13] = min(1.0, sum(1 for m in example_markers if m in answer.lower()) / 3)
        else:
            features[13] = 0.3

        # Specificity score
        features[14] = evaluation.get("specificity_score", 50) / 100

        return features

    # ── SHAP Explanations ─────────────────────────────

    def explain_score(self, evaluation: Dict[str, Any]) -> Dict[str, Any]:
        """Generate SHAP-based explanation for an interview score."""
        self._ensure_fitted()

        features = self.extract_features(evaluation)
        features_2d = features.reshape(1, -1)

        predicted_score = float(self._scoring_model.predict(features_2d)[0]) if self._scoring_model else 50.0

        # SHAP values
        shap_values = None
        feature_attributions = {}

        if SHAP_AVAILABLE and self._explainer:
            shap_values = self._explainer.shap_values(features_2d)
            for i, name in enumerate(self.FEATURE_NAMES):
                feature_attributions[name] = round(float(shap_values[0][i]), 3)
        else:
            # Fallback: approximate attributions using feature importance
            for i, name in enumerate(self.FEATURE_NAMES):
                feature_attributions[name] = round(float(features[i] * 10 - 5), 3)

        # Sort by absolute impact
        sorted_features = sorted(
            feature_attributions.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )

        # Generate dimension breakdown
        dimension_scores = self._compute_dimension_scores(features, feature_attributions)

        # Generate human-readable explanation
        explanation = self._generate_explanation(
            predicted_score, sorted_features, dimension_scores
        )

        # Generate improvement suggestions
        suggestions = self._generate_improvement_suggestions(
            features, sorted_features, dimension_scores
        )

        return {
            "predicted_score": round(predicted_score, 1),
            "feature_attributions": dict(sorted_features),
            "top_positive_factors": [
                {"feature": f, "impact": round(v, 2)}
                for f, v in sorted_features if v > 0
            ][:5],
            "top_negative_factors": [
                {"feature": f, "impact": round(v, 2)}
                for f, v in sorted_features if v < 0
            ][:5],
            "dimension_scores": dimension_scores,
            "explanation": explanation,
            "improvement_suggestions": suggestions,
            "visualization_data": self._prepare_visualization_data(
                features, feature_attributions, predicted_score
            ),
        }

    def _compute_dimension_scores(
        self, features: np.ndarray, attributions: Dict[str, float]
    ) -> Dict[str, Dict[str, Any]]:
        """Map feature attributions to high-level dimensions."""
        dimension_mapping = {
            "Communication": [
                "structural_clarity", "vocabulary_richness",
                "speaking_rate", "filler_word_ratio", "response_length",
            ],
            "Technical Depth": [
                "content_accuracy", "keyword_coverage",
                "response_depth", "specificity_score", "example_count",
            ],
            "Confidence": [
                "confidence_vocal", "confidence_facial",
                "eye_contact",
            ],
            "Emotional Regulation": [
                "emotion_stability", "stress_level",
            ],
            "Problem Solving": [
                "content_accuracy", "response_depth",
                "example_count", "specificity_score",
            ],
        }

        results = {}
        for dim_name, dim_features in dimension_mapping.items():
            dim_scores = []
            dim_attributions = []
            for f in dim_features:
                idx = self.FEATURE_NAMES.index(f) if f in self.FEATURE_NAMES else -1
                if idx >= 0:
                    dim_scores.append(float(features[idx]) * 100)
                    dim_attributions.append(attributions.get(f, 0))

            avg_score = float(np.mean(dim_scores)) if dim_scores else 50
            total_attribution = sum(dim_attributions)

            results[dim_name] = {
                "score": round(avg_score, 1),
                "attribution": round(total_attribution, 3),
                "contributing_features": {
                    f: attributions.get(f, 0) for f in dim_features
                },
                "grade": self._score_to_grade(avg_score),
            }

        return results

    def _score_to_grade(self, score: float) -> str:
        if score >= 85:
            return "Excellent"
        elif score >= 70:
            return "Good"
        elif score >= 55:
            return "Average"
        elif score >= 40:
            return "Below Average"
        return "Needs Improvement"

    # ── Human-Readable Explanations ───────────────────

    def _generate_explanation(
        self,
        score: float,
        sorted_features: List[Tuple[str, float]],
        dimension_scores: Dict[str, Dict[str, Any]],
    ) -> str:
        """Generate a clear, human-readable explanation of the score."""
        parts = []

        # Overall assessment
        if score >= 80:
            parts.append(f"Strong overall performance (score: {score:.1f}/100).")
        elif score >= 60:
            parts.append(f"Moderate performance (score: {score:.1f}/100) with room for improvement.")
        elif score >= 40:
            parts.append(f"Below-average performance (score: {score:.1f}/100). Key areas need attention.")
        else:
            parts.append(f"Significant improvement needed (score: {score:.1f}/100).")

        # Top positive factors
        positives = [(f, v) for f, v in sorted_features if v > 0][:3]
        if positives:
            pos_names = [self._feature_friendly_name(f) for f, _ in positives]
            parts.append(f"Key strengths: {', '.join(pos_names)}.")

        # Top negative factors
        negatives = [(f, v) for f, v in sorted_features if v < 0][:3]
        if negatives:
            neg_names = [self._feature_friendly_name(f) for f, _ in negatives]
            parts.append(f"Areas to improve: {', '.join(neg_names)}.")

        # Dimension highlights
        best_dim = max(dimension_scores.items(), key=lambda x: x[1]["score"])
        worst_dim = min(dimension_scores.items(), key=lambda x: x[1]["score"])

        if best_dim[1]["score"] > 70:
            parts.append(f"Your strongest dimension is {best_dim[0]} ({best_dim[1]['grade']}).")
        if worst_dim[1]["score"] < 50:
            parts.append(f"Focus on improving {worst_dim[0]} ({worst_dim[1]['grade']}).")

        return " ".join(parts)

    def _feature_friendly_name(self, feature: str) -> str:
        """Convert feature name to human-readable format."""
        names = {
            "content_accuracy": "answer accuracy",
            "keyword_coverage": "use of key terms",
            "response_depth": "depth of knowledge",
            "response_length": "answer completeness",
            "vocabulary_richness": "vocabulary diversity",
            "structural_clarity": "answer structure",
            "filler_word_ratio": "filler word usage",
            "speaking_rate": "speaking pace",
            "confidence_vocal": "vocal confidence",
            "confidence_facial": "visual confidence",
            "emotion_stability": "emotional composure",
            "stress_level": "stress management",
            "eye_contact": "eye contact",
            "example_count": "use of examples",
            "specificity_score": "answer specificity",
        }
        return names.get(feature, feature.replace("_", " "))

    # ── Improvement Suggestions ───────────────────────

    def _generate_improvement_suggestions(
        self,
        features: np.ndarray,
        sorted_features: List[Tuple[str, float]],
        dimension_scores: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Generate specific, actionable improvement suggestions."""
        suggestions = []

        # Per-feature suggestions
        feature_suggestions = {
            "content_accuracy": {
                "threshold": 0.5,
                "suggestion": "Study the core concepts for your target role. Practice explaining them in your own words with real-world examples.",
                "priority": "high",
                "category": "Technical Knowledge",
            },
            "keyword_coverage": {
                "threshold": 0.5,
                "suggestion": "Review job descriptions and include relevant industry terms and buzzwords naturally in your answers.",
                "priority": "medium",
                "category": "Technical Vocabulary",
            },
            "response_depth": {
                "threshold": 0.5,
                "suggestion": "Go beyond surface-level answers. Include specific methodologies, metrics, and lessons learned.",
                "priority": "high",
                "category": "Answer Depth",
            },
            "structural_clarity": {
                "threshold": 0.5,
                "suggestion": "Use the STAR method (Situation, Task, Action, Result) to structure your answers clearly.",
                "priority": "high",
                "category": "Communication",
            },
            "filler_word_ratio": {
                "threshold": 0.3,
                "suggestion": "Practice pausing instead of using filler words. Record yourself and count um/uh/like occurrences.",
                "priority": "medium",
                "category": "Speech Quality",
            },
            "confidence_vocal": {
                "threshold": 0.5,
                "suggestion": "Speak at a steady pace with good volume. Practice power posing before interviews to boost confidence.",
                "priority": "medium",
                "category": "Presence",
            },
            "eye_contact": {
                "threshold": 0.5,
                "suggestion": "Stay focused on the screen during the interview. Avoid looking away for extended periods.",
                "priority": "low",
                "category": "Non-verbal",
            },
            "example_count": {
                "threshold": 0.3,
                "suggestion": "Prepare 3-5 specific examples from your experience for common question types. Include metrics and outcomes.",
                "priority": "high",
                "category": "Answer Quality",
            },
            "emotion_stability": {
                "threshold": 0.5,
                "suggestion": "Practice deep breathing (box breathing: 4s in, 4s hold, 4s out, 4s hold) to maintain composure under pressure.",
                "priority": "medium",
                "category": "Emotional Intelligence",
            },
        }

        for feat_name, config in feature_suggestions.items():
            idx = self.FEATURE_NAMES.index(feat_name) if feat_name in self.FEATURE_NAMES else -1
            if idx >= 0 and features[idx] < config["threshold"]:
                suggestions.append({
                    "feature": feat_name,
                    "current_score": round(float(features[idx]) * 100, 1),
                    "suggestion": config["suggestion"],
                    "priority": config["priority"],
                    "category": config["category"],
                })

        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda x: priority_order.get(x["priority"], 3))

        return suggestions[:8]

    # ── Visualization Data ────────────────────────────

    def _prepare_visualization_data(
        self,
        features: np.ndarray,
        attributions: Dict[str, float],
        base_score: float,
    ) -> Dict[str, Any]:
        """Prepare data for frontend visualization (waterfall, bar, radar)."""
        # Waterfall chart data
        waterfall = []
        running_total = base_score / 2  # Start from base value
        for name in self.FEATURE_NAMES:
            impact = attributions.get(name, 0)
            waterfall.append({
                "feature": self._feature_friendly_name(name),
                "impact": round(impact, 2),
                "running_total": round(running_total + impact, 2),
            })
            running_total += impact

        # Bar chart: feature importance
        bar_data = [
            {
                "feature": self._feature_friendly_name(name),
                "value": round(float(features[i]) * 100, 1),
                "attribution": round(attributions.get(name, 0), 2),
            }
            for i, name in enumerate(self.FEATURE_NAMES)
        ]
        bar_data.sort(key=lambda x: abs(x["attribution"]), reverse=True)

        # Radar chart: dimension scores
        radar_data = {
            dim: scores["score"]
            for dim, scores in self._compute_dimension_scores(features, attributions).items()
        }

        return {
            "waterfall": waterfall,
            "bar": bar_data[:10],
            "radar": radar_data,
        }


# Singleton
explainability_service = ExplainabilityService()
