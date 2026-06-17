#!/bin/bash
set -e

echo "📦 Building Backend Helper VS Code Extension..."

# Navigate to the extension directory
cd "$(dirname "$0")/.."

echo "📥 Installing dependencies..."
npm install

echo "🛠️ Compiling TypeScript..."
npm run compile

echo "📦 Packaging with vsce..."
# Check if vsce is installed, if not try to use npx
if command -v vsce &> /dev/null; then
    vsce package
else
    echo "vsce not found, using npx..."
    npx @vscode/vsce package
fi

echo "✅ Build and package complete! You can install the .vsix file now."
