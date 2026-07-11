using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;

namespace MyProject.Models
{
    public class User
    {
        [Key]
        public int Id { get; set; }
        
        [Required]
        public string Name { get; set; }
        
        public virtual ICollection<Post> Posts { get; set; }
        
        public void AddPost(Post post)
        {
            this.Posts.Add(post);
        }
    }
}
