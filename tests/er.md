erDiagram
    Post {
        int_PK PostId
        string Content
        int UserId
    }
    User {
        int_PK Id
        string Name
    }
    User ||--o{ Post : "Posts"