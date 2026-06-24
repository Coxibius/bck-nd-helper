"""
Infrastructure Parser - Docker Compose Visualization Module

Parses docker-compose.yml files and generates Mermaid infrastructure diagrams
showing service dependencies and relationships.
"""

import yaml
from pathlib import Path
from typing import Optional, Dict, Any, List

# Database image keywords for shape detection
DB_IMAGES = ['postgres', 'mysql', 'redis', 'mongo', 'mariadb', 'cassandra', 'mongodb', 'elasticsearch']


def parse_infra(root_path: str) -> Optional[str]:
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
    
    for filename in compose_files:
        compose_path = root / filename
        if compose_path.exists() and compose_path.is_file():
            return str(compose_path)
    
    return None


def parse_docker_compose(file_path: str) -> Dict[str, Any]:
    """
    Parses docker-compose YAML file and extracts services.
    
    Args:
        file_path: Path to docker-compose file
        
    Returns:
        Dictionary of services from the compose file
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            compose_data = yaml.safe_load(f)
        
        # Return services dictionary, or empty dict if not found
        return compose_data.get('services', {})
    
    except yaml.YAMLError as e:
        print(f"Error parsing YAML: {e}")
        return {}
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return {}
    except Exception as e:
        print(f"Unexpected error: {e}")
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


def scan_infra(root_path: str) -> Optional[str]:
    """
    Complete workflow: finds docker-compose, parses it, and generates Mermaid diagram.
    
    Args:
        root_path: Root directory to scan
        
    Returns:
        Mermaid graph code, or None if no compose file found
    """
    compose_file = parse_infra(root_path)
    
    if not compose_file:
        return None
    
    services = parse_docker_compose(compose_file)
    return generate_mermaid_infra(services)
