from typing import Any

from mcp.server.mcpserver import MCPServer

import purplemd
from purplemd_storage import get_storage

mcp = MCPServer("PurpleMD")


def storage():
    return get_storage()


def project_to_dict(project: Any) -> dict[str, Any]:
    return {
        "name": project.name,
        "modified": project.modified,
    }


def note_to_dict(note: Any) -> dict[str, Any]:
    return {
        "project": note.project,
        "path": note.path,
        "content": note.content,
        "modified": note.modified,
    }


@mcp.tool()
def list_projects() -> dict[str, Any]:
    """Lista todos los proyectos disponibles en PurpleMD."""
    projects = purplemd.listar_proyectos(
        storage=storage(),
    )

    return {
        "projects": [
            project_to_dict(project)
            for project in projects
        ]
    }


@mcp.tool()
def get_project_tree(project: str) -> dict[str, Any]:
    """Obtiene el árbol de carpetas y notas de un proyecto.

    Args:
        project: Nombre exacto del proyecto.
    """
    tree = purplemd.arbol_proyecto(
        project,
        storage=storage(),
    )

    return {
        "project": tree.project,
        "entries": [
            {
                "type": entry.type,
                "path": entry.path,
                "modified": entry.modified,
            }
            for entry in tree.entries
        ],
    }


@mcp.tool()
def read_note(
    project: str,
    path: str,
) -> dict[str, Any]:
    """Lee el contenido completo de una nota Markdown.

    Args:
        project: Nombre del proyecto.
        path: Ruta de la nota dentro del proyecto.
    """
    note = purplemd.leer_nota(
        project,
        path,
        storage=storage(),
    )

    return note_to_dict(note)


@mcp.tool()
def create_note(
    project: str,
    path: str,
    content: str,
) -> dict[str, Any]:
    """Crea una nueva nota Markdown.

    Args:
        project: Nombre del proyecto.
        path: Ruta de la nota, por ejemplo 'docs/arquitectura.md'.
        content: Contenido Markdown de la nueva nota.
    """
    note = purplemd.crear_nota(
        project,
        path,
        content,
        storage=storage(),
    )

    return note_to_dict(note)


@mcp.tool()
def update_note(
    project: str,
    path: str,
    content: str,
) -> dict[str, Any]:
    """Reemplaza completamente el contenido de una nota.

    Args:
        project: Nombre del proyecto.
        path: Ruta de la nota.
        content: Nuevo contenido Markdown.
    """
    note = purplemd.guardar_nota(
        project,
        path,
        content,
        storage=storage(),
    )

    return note_to_dict(note)


@mcp.tool()
def move_note(
    project: str,
    path: str,
    destination: str,
) -> dict[str, Any]:
    """Mueve o renombra una nota.

    Args:
        project: Nombre del proyecto.
        path: Ruta actual de la nota.
        destination: Nueva ruta de la nota.
    """
    note = purplemd.mover_nota(
        project,
        path,
        destination,
        storage=storage(),
    )

    return note_to_dict(note)


@mcp.tool()
def delete_note(
    project: str,
    path: str,
) -> dict[str, Any]:
    """Elimina una nota Markdown.

    Esta operación es irreversible.

    Args:
        project: Nombre del proyecto.
        path: Ruta de la nota.
    """
    purplemd.eliminar_nota(
        project,
        path,
        storage=storage(),
    )

    return {
        "deleted": True,
        "project": project,
        "path": path,
    }

