"""Servidor MCP de PurpleMD: las herramientas y el punto de entrada del transporte.

Las herramientas son una fachada delgada sobre `purplemd` (el núcleo de
negocio). Lo único propio de este módulo es **de dónde salen los datos**: la
identidad de quien llama vive en la cabecera HTTP del mensaje MCP
(`ctx.headers`), no en una sesión, así que el storage se resuelve por request.

Ese resolutor lo implementa `api.py`, que es donde están la sesión, el entorno
y las tres variantes de storage; acá solo se declara el contrato (ver
`registrar_almacenamiento`). Invertir la dependencia así evita un ciclo de
imports y deja este módulo sin conocimiento de HTTP ni de Google.
"""

from collections.abc import Callable, Mapping
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

import purplemd
from purplemd_storage import Storage

mcp = MCPServer("PurpleMD")

# Contrato: entran las cabeceras del request que trajo este mensaje MCP y sale
# el storage con el que trabaja el tool. `None` (transporte sin HTTP, p. ej.
# stdio) lo decide el implementador.
AlmacenamientoMcp = Callable[[Mapping[str, str] | None], Storage]
_almacenamiento: AlmacenamientoMcp | None = None


def registrar_almacenamiento(funcion: AlmacenamientoMcp) -> None:
    """Fija el resolutor de storage. Lo llama `api.py` al importarse.

    Sin resolutor registrado no hay herramientas que puedan correr: el fallo
    es ruidoso (una excepción por request) y no un storage por defecto, que
    sería un acceso a los datos de otro.
    """
    global _almacenamiento
    _almacenamiento = funcion


def storage(ctx: Context) -> Storage:
    """Storage de este tool: el que corresponde al token de este request."""
    if _almacenamiento is None:
        raise RuntimeError("el resolutor de storage del MCP no está registrado")
    return _almacenamiento(ctx.headers)


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
def list_projects(ctx: Context) -> dict[str, Any]:
    """Lista todos los proyectos disponibles en PurpleMD."""
    projects = purplemd.listar_proyectos(
        storage=storage(ctx),
    )

    return {
        "projects": [
            project_to_dict(project)
            for project in projects
        ]
    }


@mcp.tool()
def get_project_tree(project: str, ctx: Context) -> dict[str, Any]:
    """Obtiene el árbol de carpetas y notas de un proyecto.

    Args:
        project: Nombre exacto del proyecto.
    """
    tree = purplemd.arbol_proyecto(
        project,
        storage=storage(ctx),
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
    ctx: Context,
) -> dict[str, Any]:
    """Lee el contenido completo de una nota Markdown.

    Args:
        project: Nombre del proyecto.
        path: Ruta de la nota dentro del proyecto.
    """
    note = purplemd.leer_nota(
        project,
        path,
        storage=storage(ctx),
    )

    return note_to_dict(note)


@mcp.tool()
def create_note(
    project: str,
    path: str,
    content: str,
    ctx: Context,
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
        storage=storage(ctx),
    )

    return note_to_dict(note)


@mcp.tool()
def update_note(
    project: str,
    path: str,
    content: str,
    ctx: Context,
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
        storage=storage(ctx),
    )

    return note_to_dict(note)


@mcp.tool()
def move_note(
    project: str,
    path: str,
    destination: str,
    ctx: Context,
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
        storage=storage(ctx),
    )

    return note_to_dict(note)


@mcp.tool()
def delete_note(
    project: str,
    path: str,
    ctx: Context,
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
        storage=storage(ctx),
    )

    return {
        "deleted": True,
        "project": project,
        "path": path,
    }
