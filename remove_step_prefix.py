import os
import re
import glob

steps_dir = "/Users/hoojinguyen/Projects/vocab-craft-engine/src/pipeline/steps"
files = glob.glob(os.path.join(steps_dir, "*.py"))

pattern = re.compile(r'\[Step \d+\]\s*')

for filepath in files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = pattern.sub('', content)
    
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")
