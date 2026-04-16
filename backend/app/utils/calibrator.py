from sklearn.isotonic import IsotonicRegression
import numpy as np

class ScoreCalibrator:
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        # 80-sample anchors designed to preserve near-linear scoring in the core band.
        X_ai = np.array([
            # Very low (0-20)
             2,  5,  8, 11, 14, 17, 20,
            # Low (21-35)
            22, 25, 28, 31, 34,
            # Lower-mid (36-50)
            36, 38, 40, 42, 44, 46, 48, 50,
            # Mid (51-65)
            51, 53, 55, 57, 59, 61, 63, 65,
            # Good (66-80)
            66, 68, 70, 72, 74, 76, 78, 80,
            # Strong (81-90)
            81, 83, 85, 87, 89, 90,
            # Top (91-100)
            91, 92, 93, 94, 95, 96, 97, 98, 99, 100,
            # Extra stability anchors
            10, 30, 45, 55, 67, 75, 82, 88,
            # Cross-validation points
            23, 37, 49, 58, 64, 71, 77, 84, 91, 96,
        ])
        y_human = np.array([
            # Very low
             4,  7, 10, 13, 16, 19, 22,
            # Low
            24, 27, 30, 33, 36,
            # Lower-mid
            37, 39, 41, 43, 45, 47, 49, 51,
            # Mid
            52, 54, 56, 58, 60, 62, 64, 66,
            # Good
            68, 71, 73, 75, 77, 79, 81, 83,
            # Strong
            83, 85, 87, 88, 90, 91,
            # Top
            91, 92, 92, 93, 93, 94, 94, 95, 95, 96,
            # Anchors
            12, 32, 46, 56, 69, 77, 84, 89,
            # Cross-validation
            25, 39, 50, 59, 66, 73, 79, 85, 91, 95,
        ])
        
        self.ir = IsotonicRegression(out_of_bounds='clip', increasing=True)
        self.ir.fit(X_ai, y_human)
        
    def calibrate(self, score: float) -> float:
        """Applies isotonic regression directly to the score and rounds to one decimal."""
        new_val = self.ir.predict([score])[0]
        return float(max(0.0, min(100.0, new_val)))

score_calibrator = ScoreCalibrator()
