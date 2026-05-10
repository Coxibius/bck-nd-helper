import tree_sitter
import tree_sitter_c_sharp

try:
    LANGUAGE = tree_sitter.Language(tree_sitter_c_sharp.language())
    parser = tree_sitter.Parser(LANGUAGE)
    
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
    tree = parser.parse(code)
    root_node = tree.root_node
    print(f"Parsed root: {root_node.type}")
    print("Success!")
except Exception as e:
    print(f"Error: {e}")
