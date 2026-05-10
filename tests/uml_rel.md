classDiagram
    namespace Root {
      class Post {
        +int PostId
        +string Content
        +int UserId
      }
      class User {
        +int Id
        +string Name
        +ICollection<Post> Posts
        +AddPost(Post post)
      }
    }
    User --> Post