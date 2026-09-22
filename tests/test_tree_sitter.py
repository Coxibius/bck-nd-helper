"""Parsing smoke test for the C# Tree-sitter grammar, not the UML extractor."""

import tree_sitter
import tree_sitter_c_sharp


def test_csharp_example_parses_without_syntax_errors():
    language = tree_sitter.Language(tree_sitter_c_sharp.language())
    parser = tree_sitter.Parser(language)

    code = b"""
    using System;
    using System.Collections.Generic;
    using System.ComponentModel.DataAnnotations;

    namespace MyProject.Models {
        public class User : BaseEntity {
            [Key]
            public int Id { get; set; }

            [Required]
            public string Name { get; set; }

            public virtual ICollection<Post> Posts { get; set; }

            public void AddPost(Post post) {
                this.Posts.Add(post);
            }
        }
    }
    """

    root = parser.parse(code).root_node
    nodes = [root]
    for node in nodes:
        nodes.extend(node.named_children)

    assert root.type == "compilation_unit"
    assert not root.has_error
    assert any(node.type == "class_declaration" for node in nodes)
    assert any(node.type == "method_declaration" for node in nodes)
