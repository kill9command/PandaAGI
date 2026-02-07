#!/bin/bash
# Update all imports after directory restructure

echo "Updating Python imports: gateway → lib.gateway"

# Find all Python files and update gateway imports
find . -name "*.py" -not -path "./__pycache__/*" -not -path "./lib/__pycache__/*" -not -path "./apps/__pycache__/*" -exec sed -i 's/from gateway\./from lib.gateway./g' {} \;
find . -name "*.py" -not -path "./__pycache__/*" -not -path "./lib/__pycache__/*" -not -path "./apps/__pycache__/*" -exec sed -i 's/import gateway\./import lib.gateway./g' {} \;

echo "Updating shell scripts: project_build_instructions → apps"

# Update start.sh
sed -i 's/project_build_instructions\.gateway\.app/apps.gateway.app/g' start.sh
sed -i 's/project_build_instructions\.orchestrator\.app/apps.orchestrator.app/g' start.sh

# Update stop.sh
sed -i 's/project_build_instructions\.gateway\.app/apps.gateway.app/g' stop.sh
sed -i 's/project_build_instructions\.orchestrator\.app/apps.orchestrator.app/g' stop.sh

echo "Import updates complete!"
