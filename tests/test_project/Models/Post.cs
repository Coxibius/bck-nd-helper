using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace MyProject.Models
{
    public class Post
    {
        [Key]
        public int PostId { get; set; }
        
        public string Content { get; set; }
        
        [ForeignKey("User")]
        public int UserId { get; set; }
        
        public virtual User User { get; set; }
    }
}
