"""
Infrastructure Parser - Docker Compose Visualization Module

Parses docker-compose.yml files and generates Mermaid infrastructure diagrams
showing service dependencies and relationships.
"""

import yaml
from pathlib import Path
from typing import Optional, Dict, Any, List
from bck_nd_hlpr.core.utils.cache import FileCache
from bck_nd_hlpr.core.utils.indexer import FileIndex, FileSystemIndexer

# Database image keywords for shape detection
DB_IMAGES = ['postgres', 'mysql', 'redis', 'mongo', 'mariadb', 'cassandra', 'mongodb', 'elasticsearch']


def parse_infra(
    root_path: str,
    *,
    file_index: Optional[FileIndex] = None,
) -> Optional[str]:
    """
    Scans for docker-compose files in the root directory.
    
    Args:
        root_path: Root directory to scan
        
    Returns:
        Path to first found docker-compose file, or None
    """
    root = Path(root_path)
    
    # Common docker-compose file names
    compose_files = [
        'docker-compose.yml',
        'docker-compose.yaml',
        'compose.yml',
        'compose.yaml'
    ]
    
    try:
        snapshot = file_index or FileSystemIndexer(str(root)).build()
    except (OSError, RuntimeError, ValueError):
        return None

    indexed = {path.name: path for path in snapshot.all_files if path.parent == snapshot.root}
    for filename in compose_files:
        compose_path = indexed.get(filename)
        if compose_path is not None:
            return str(compose_path)
    
    return None


def parse_docker_compose(
    file_path: str,
    *,
    project_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parses docker-compose YAML file and extracts services.
    
    Args:
        file_path: Path to docker-compose file
        
    Returns:
        Dictionary of services from the compose file
    """
    try:
        root = Path(project_root) if project_root is not None else Path(file_path).parent
        compose_data = yaml.safe_load(FileCache.read_project_file(root, file_path))

        # Return services dictionary, or empty dict if not found
        if not isinstance(compose_data, dict):
            return {}
        services = compose_data.get('services', {})
        return services if isinstance(services, dict) else {}

    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError):
        return {}


def is_database(service_info: Dict[str, Any]) -> bool:
    """
    Determines if a service is a database based on its image name.
    
    Args:
        service_info: Service configuration dictionary
        
    Returns:
        True if service is a database, False otherwise
    """
    image = service_info.get('image', '').lower()
    return any(db in image for db in DB_IMAGES)


def generate_mermaid_infra(services: Dict[str, Any]) -> str:
    """
    Generates Mermaid graph code from docker-compose services.
    
    Args:
        services: Dictionary of services from docker-compose
        
    Returns:
        Mermaid graph LR code as string
    """
    if not services:
        return "graph LR\n    empty[No services found]"
    
    import re
    def sanitize_id(name: str) -> str:
        s = re.sub(r'[^A-Za-z0-9_]', '_', str(name).strip())
        if not s: return "srv_unknown"
        if not s[0].isalpha():
            s = 'srv_' + s
        return s

    lines = ["graph LR"]
    edges = []
    
    # Generate nodes
    for service_name, service_config in services.items():
        safe_id = sanitize_id(service_name)
        # Determine label (image or build info)
        if 'image' in service_config:
            label = f"{service_name} (image: {service_config['image']})"
        elif 'build' in service_config:
            build_path = service_config['build']
            if isinstance(build_path, dict):
                build_path = build_path.get('context', '.')
            label = f"{service_name} (build: {build_path})"
        else:
            label = service_name
        
        # Clean label (quotes and newlines)
        clean_label = " ".join(label.split()).replace('"', "'")
        
        # Determine shape based on service type
        if is_database(service_config):
            # Cylinder shape for databases
            node = f'    {safe_id}[("{clean_label}")]'
        else:
            # Box shape for regular services
            node = f'    {safe_id}["{clean_label}"]'
        
        lines.append(node)
        
        # Extract dependencies for edges
        depends_on = service_config.get('depends_on', [])
        
        # depends_on can be a list or dict (with conditions)
        if isinstance(depends_on, dict):
            depends_on = list(depends_on.keys())
        elif not isinstance(depends_on, list):
            depends_on = []
        
        for dependency in depends_on:
            edges.append(f'    {safe_id} --> {sanitize_id(dependency)}')
        
        # Also check for 'links' (older docker-compose syntax)
        links = service_config.get('links', [])
        for link in links:
            # Links can be "service" or "service:alias"
            linked_service = link.split(':')[0]
            edge = f'    {safe_id} --> {sanitize_id(linked_service)}'
            if edge not in edges:  # Avoid duplicates
                edges.append(edge)
    
    # Add edges
    if edges:
        lines.append("")
        lines.extend(edges)
    
    return '\n'.join(lines)


def scan_infra(
    root_path: str,
    *,
    file_index: Optional[FileIndex] = None,
) -> Optional[str]:
    """
    Complete workflow: finds docker-compose, parses it, and generates Mermaid diagram.
    
    Args:
        root_path: Root directory to scan
        
    Returns:
        Mermaid graph code, or None if no compose file found
    """
    compose_file = parse_infra(root_path, file_index=file_index)
    
    if not compose_file:
        return None
    
    services = parse_docker_compose(compose_file, project_root=root_path)
    return generate_mermaid_infra(services)
