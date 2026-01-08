"""
Scene Analyzer Module - Multi-modal analysis for intelligent reframing
Uses YOLO for object detection, motion analysis, and scene classification.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum


class SceneType(Enum):
    """Classification of scene types for reframing strategy"""
    DIALOGUE = "dialogue"      # Talking heads, focus on speaker
    ACTION = "action"          # High motion, follow action center
    TEXT = "text"              # On-screen text/graphics, static crop
    MIXED = "mixed"            # Ambiguous, needs LLM guidance


@dataclass
class Detection:
    """Object detection result"""
    class_name: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2
    center: Tuple[int, int]
    area: int


@dataclass
class FrameAnalysis:
    """Complete analysis of a single frame"""
    timestamp: float
    scene_type: SceneType
    faces: List[Detection]
    persons: List[Detection]
    motion_magnitude: float
    motion_direction: Optional[Tuple[float, float]]  # (dx, dy) normalized
    suggested_focus: Tuple[int, int]  # (x, y) center point
    confidence: float
    is_scene_change: bool = False


class SceneAnalyzer:
    """
    Analyzes video frames for intelligent reframing decisions.
    Uses YOLOv8x for object detection and OpenCV for motion analysis.
    """
    
    def __init__(self, model_size: str = "x"):
        """
        Initialize analyzer with YOLO model.
        
        Args:
            model_size: YOLO model size - 'n', 's', 'm', 'l', 'x' (default: 'x' for best accuracy)
        """
        self.model = None
        self.model_size = model_size
        self.prev_frame_gray = None
        self.prev_hist = None
        
    def _load_yolo(self):
        """Lazy load YOLO model"""
        if self.model is None:
            from ultralytics import YOLO
            model_name = f"yolov8{self.model_size}.pt"
            print(f"    Loading YOLO model: {model_name}")
            self.model = YOLO(model_name)
    
    def detect_objects(self, frame: np.ndarray) -> Tuple[List[Detection], List[Detection]]:
        """
        Detect faces and persons in frame using YOLO.
        
        Returns:
            Tuple of (faces, persons) Detection lists
        """
        self._load_yolo()
        
        # Run YOLO inference
        results = self.model(frame, verbose=False, classes=[0])  # class 0 = person
        
        persons = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                cls_name = result.names[cls_id]
                
                center = ((x1 + x2) // 2, (y1 + y2) // 2)
                area = (x2 - x1) * (y2 - y1)
                
                persons.append(Detection(
                    class_name=cls_name,
                    confidence=conf,
                    bbox=(x1, y1, x2, y2),
                    center=center,
                    area=area
                ))
        
        # Sort by area (largest first - likely primary subject)
        persons.sort(key=lambda d: d.area, reverse=True)
        
        # For faces, we still use MediaPipe for better face-specific detection
        faces = self._detect_faces_mediapipe(frame)
        
        return faces, persons
    
    def _detect_faces_mediapipe(self, frame: np.ndarray) -> List[Detection]:
        """Detect faces using MediaPipe for better accuracy"""
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        import urllib.request
        
        model_path = Path(__file__).parent / "face_detector.tflite"
        if not model_path.exists():
            url = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
            urllib.request.urlretrieve(url, str(model_path))
        
        base_options = python.BaseOptions(model_asset_path=str(model_path))
        options = vision.FaceDetectorOptions(base_options=base_options)
        detector = vision.FaceDetector.create_from_options(options)
        
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        
        results = detector.detect(mp_image)
        detector.close()
        
        faces = []
        for detection in results.detections:
            bbox = detection.bounding_box
            x1, y1 = bbox.origin_x, bbox.origin_y
            x2, y2 = x1 + bbox.width, y1 + bbox.height
            center = (x1 + bbox.width // 2, y1 + bbox.height // 2)
            area = bbox.width * bbox.height
            
            faces.append(Detection(
                class_name="face",
                confidence=detection.categories[0].score if detection.categories else 0.5,
                bbox=(x1, y1, x2, y2),
                center=center,
                area=area
            ))
        
        faces.sort(key=lambda d: d.area, reverse=True)
        return faces
    
    def compute_motion(self, frame: np.ndarray) -> Tuple[float, Optional[Tuple[float, float]]]:
        """
        Compute motion magnitude and direction using optical flow.
        
        Returns:
            Tuple of (magnitude 0-1, direction (dx, dy) normalized or None)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        
        if self.prev_frame_gray is None:
            self.prev_frame_gray = gray
            return 0.0, None
        
        # Compute frame difference
        frame_diff = cv2.absdiff(self.prev_frame_gray, gray)
        _, thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)
        
        # Calculate motion magnitude as percentage of frame with motion
        motion_pixels = np.count_nonzero(thresh)
        total_pixels = thresh.shape[0] * thresh.shape[1]
        magnitude = min(motion_pixels / total_pixels * 10, 1.0)  # Scale and cap at 1.0
        
        # Calculate motion center for direction
        moments = cv2.moments(thresh)
        direction = None
        if moments["m00"] > 0:
            cx = int(moments["m10"] / moments["m00"])
            cy = int(moments["m01"] / moments["m00"])
            frame_cx, frame_cy = frame.shape[1] // 2, frame.shape[0] // 2
            dx = (cx - frame_cx) / frame.shape[1]
            dy = (cy - frame_cy) / frame.shape[0]
            direction = (dx, dy)
        
        self.prev_frame_gray = gray
        return magnitude, direction
        
    def detect_scene_change(self, frame: np.ndarray) -> bool:
        """
        Detect if a sharp scene change has occurred using histogram comparison.
        """
        # Calculate histogram (using HSV for better color robustness)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        
        is_cut = False
        if self.prev_hist is not None:
            # Compare with correlation
            score = cv2.compareHist(self.prev_hist, hist, cv2.HISTCMP_CORREL)
            # Low correlation score indicates scene change (e.g. < 0.6)
            if score < 0.6:
                is_cut = True
        
        self.prev_hist = hist
        return is_cut
    
    def classify_scene(
        self,
        faces: List[Detection],
        persons: List[Detection],
        motion_magnitude: float
    ) -> SceneType:
        """
        Classify scene type based on detections and motion.
        """
        has_faces = len(faces) > 0
        has_persons = len(persons) > 0
        high_motion = motion_magnitude > 0.3
        
        if has_faces and not high_motion:
            return SceneType.DIALOGUE
        elif high_motion and (has_persons or not has_faces):
            return SceneType.ACTION
        elif not has_faces and not has_persons and not high_motion:
            return SceneType.TEXT
        else:
            return SceneType.MIXED
    
    def suggest_focus_point(
        self,
        frame: np.ndarray,
        faces: List[Detection],
        persons: List[Detection],
        motion_direction: Optional[Tuple[float, float]],
        scene_type: SceneType
    ) -> Tuple[Tuple[int, int], float]:
        """
        Suggest optimal focus point based on analysis.
        
        Returns:
            Tuple of ((x, y) focus point, confidence 0-1)
        """
        h, w = frame.shape[:2]
        center = (w // 2, h // 2)
        
        if scene_type == SceneType.DIALOGUE and faces:
            # Focus on largest face
            return faces[0].center, 0.9
        
        elif scene_type == SceneType.ACTION and persons:
            # Focus on largest person with motion bias
            focus = persons[0].center
            if motion_direction:
                # Bias slightly towards motion direction
                dx, dy = motion_direction
                focus = (
                    int(focus[0] + dx * w * 0.1),
                    int(focus[1] + dy * h * 0.1)
                )
            return focus, 0.7
        
        elif scene_type == SceneType.TEXT:
            # Center crop for text
            return center, 0.8
        
        else:  # MIXED - lower confidence, may need LLM
            if faces:
                return faces[0].center, 0.5
            elif persons:
                return persons[0].center, 0.5
            else:
                return center, 0.3
    
    def analyze_frame(self, frame: np.ndarray, timestamp: float) -> FrameAnalysis:
        """
        Perform complete analysis of a single frame.
        """
        faces, persons = self.detect_objects(frame)
        motion_mag, motion_dir = self.compute_motion(frame)
        is_scene_change = self.detect_scene_change(frame)
        
        scene_type = self.classify_scene(faces, persons, motion_mag)
        focus, confidence = self.suggest_focus_point(
            frame, faces, persons, motion_dir, scene_type
        )
        
        return FrameAnalysis(
            timestamp=timestamp,
            scene_type=scene_type,
            faces=faces,
            persons=persons,
            motion_magnitude=motion_mag,
            motion_direction=motion_dir,
            suggested_focus=focus,
            confidence=confidence,
            is_scene_change=is_scene_change
        )
    
    def analyze_video_segment(
        self,
        video_path: Path,
        start: float = 0,
        end: float = None,
        sample_interval: float = 0.5
    ) -> List[FrameAnalysis]:
        """
        Analyze a video segment at regular intervals.
        
        ENHANCED: Now includes explicit t=0 first-frame analysis and CSRT tracking.
        
        Args:
            video_path: Path to video file
            start: Start time in seconds
            end: End time in seconds (None = to end)
            sample_interval: Seconds between samples
            
        Returns:
            List of FrameAnalysis for each sampled frame
        """
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        
        if end is None:
            end = duration
        
        # Reset motion tracking and scene history
        self.prev_frame_gray = None
        self.prev_hist = None
        
        analyses = []
        tracker = None
        tracking_bbox = None
        
        # CRITICAL: Always analyze first frame (t=0) explicitly
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(start * fps))
        ret, first_frame = cap.read()
        
        if ret:
            # Analyze first frame at t=0
            first_analysis = self.analyze_frame(first_frame, 0.0)
            analyses.append(first_analysis)
            
            # Initialize CSRT tracker if we found a subject
            if first_analysis.faces or first_analysis.persons:
                # Use the primary subject (face preferred, then person)
                if first_analysis.faces:
                    bbox = first_analysis.faces[0].bbox
                elif first_analysis.persons:
                    bbox = first_analysis.persons[0].bbox
                else:
                    bbox = None
                
                if bbox:
                    # Convert (x1, y1, x2, y2) to (x, y, w, h) for OpenCV
                    x1, y1, x2, y2 = bbox
                    tracking_bbox = (x1, y1, x2 - x1, y2 - y1)
                    tracker = cv2.TrackerCSRT_create()
                    tracker.init(first_frame, tracking_bbox)
        
        # Continue with regular interval sampling
        current_time = sample_interval  # Start after first frame
        
        while current_time < end:
            frame_num = int((start + current_time) * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            
            ret, frame = cap.read()
            if not ret:
                break
            
            # Run YOLO analysis at each sample point
            analysis = self.analyze_frame(frame, current_time)
            
            # Reset tracker if scene changed entirely
            if analysis.is_scene_change:
                tracker = None
                tracking_bbox = None
            
            # If YOLO detection confidence is low, use CSRT tracker
            if tracker is not None and analysis.confidence < 0.6:
                success, tracked_box = tracker.update(frame)
                if success:
                    x, y, w, h = [int(v) for v in tracked_box]
                    tracked_center = (x + w // 2, y + h // 2)
                    # Use tracked position but keep the analysis metadata
                    analysis = FrameAnalysis(
                        timestamp=current_time,
                        scene_type=analysis.scene_type,
                        faces=analysis.faces,
                        persons=analysis.persons,
                        motion_magnitude=analysis.motion_magnitude,
                        motion_direction=analysis.motion_direction,
                        suggested_focus=tracked_center,
                        confidence=0.75,  # Tracker confidence
                        is_scene_change=analysis.is_scene_change
                    )
            
            # Re-initialize tracker if we got high-confidence YOLO detection OR scene changed
            if (analysis.confidence >= 0.8 and (analysis.faces or analysis.persons)) or (analysis.is_scene_change and (analysis.faces or analysis.persons)):
                if analysis.faces:
                    bbox = analysis.faces[0].bbox
                elif analysis.persons:
                    bbox = analysis.persons[0].bbox
                else:
                    bbox = None
                    
                if bbox:
                    x1, y1, x2, y2 = bbox
                    tracking_bbox = (x1, y1, x2 - x1, y2 - y1)
                    tracker = cv2.TrackerCSRT_create()
                    tracker.init(frame, tracking_bbox)
            
            analyses.append(analysis)
            current_time += sample_interval
        
        cap.release()
        return analyses
    
    def get_dominant_scene_type(self, analyses: List[FrameAnalysis]) -> SceneType:
        """Get the most common scene type from analyses"""
        if not analyses:
            return SceneType.MIXED
        
        type_counts = {}
        for a in analyses:
            type_counts[a.scene_type] = type_counts.get(a.scene_type, 0) + 1
        
        return max(type_counts, key=type_counts.get)
