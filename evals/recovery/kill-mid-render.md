# Recovery: kill-mid-render

Kill clips.py during clip 3. Expected: clips 1-2 exist with sidecars, clip 3 has no sidecar, manifest is absent, `clips.py --only 3` resumes without redoing 1-2.
