---
{"id": "ai_ml-cs-defect-vision", "type": "case_study", "persona": "ai_ml", "project": "defect-vision", "skills": ["Computer Vision", "Deep Learning", "PyTorch", "OpenCV", "Image Processing"], "date": "2023-01-01", "client_industry": "Manufacturing", "synthetic": true}
---
# Visual defect detection on a bottling line

**Client:** a Faisalabad beverage manufacturer  
**Industry:** Manufacturing  
**Year:** 2023

## The problem
Cracked and under-filled bottles were caught by eye at 120 bottles per minute.

## What I did
Trained a YOLO-style detector on 6,200 labelled frames with heavy augmentation, exported to ONNX and ran it on an edge PC beside the conveyor.

## Outcome
Recall on defects reached 96% at 2% false alarms; ran at 45 FPS on CPU.

**Skills:** Computer Vision, Deep Learning, PyTorch, OpenCV, Image Processing
