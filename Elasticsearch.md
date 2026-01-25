# Elasticsearch:

## creator-entities (Creator nodes)

Deterministic _id: creator:<uuid-or-hash> (your system’s ID)

```json
PUT creator-entities
{
  "settings": { "number_of_shards": 1, "number_of_replicas": 1 },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "creator_id": { "type": "keyword" },
      "canonical_name": { "type": "keyword" },
      "type": { "type": "keyword" }, 
      "aliases": { "type": "keyword" },

      "created_at": { "type": "date" },
      "updated_at": { "type": "date" },

      "external_ids": {
        "type": "object",
        "dynamic": "strict",
        "properties": {
          "youtube_channel_id": { "type": "keyword" },
          "instagram_username": { "type": "keyword" },
          "twitter_username": { "type": "keyword" },
          "website_domain": { "type": "keyword" }
        }
      },

      "notes": { "type": "text" }
    }
  }
}
```
___

## creator-accounts (Account nodes)

Deterministic _id: <platform>:<account_id>
For TikTok: tiktok:<uploader_id> (matches your state ID scheme)

```json
PUT creator-accounts
{
  "settings": { "number_of_shards": 1, "number_of_replicas": 1 },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "account_id": { "type": "keyword" },          
      "platform": { "type": "keyword" },            
      "platform_account_id": { "type": "keyword" }, 
      "handle": { "type": "keyword" },              
      "display_name": { "type": "keyword" },        
      "profile_url": { "type": "keyword" },

      "status": { "type": "keyword" },              
      "first_seen": { "type": "date" },
      "last_seen": { "type": "date" },

      "signals": {
        "type": "object",
        "dynamic": "strict",
        "properties": {
          "website_domains": { "type": "keyword" },
          "youtube_channel_ids": { "type": "keyword" },
          "instagram_usernames": { "type": "keyword" },
          "twitter_usernames": { "type": "keyword" },
          "emails": { "type": "keyword" }
        }
      },

      "updated_at": { "type": "date" }
    }
  }
}
```
___

## creator-account-links (Edges)

Deterministic _id: link:<creator_id>:<account_id>

This is where you store:

- confidence score

- reasons/signals that justify the link

- when it was created/updated

- (optional) "human approved” flag

```json
PUT creator-entities
{
  "settings": { "number_of_shards": 1, "number_of_replicas": 1 },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "creator_id": { "type": "keyword" },
      "canonical_name": { "type": "keyword" },
      "type": { "type": "keyword" }, 
      "aliases": { "type": "keyword" },

      "created_at": { "type": "date" },
      "updated_at": { "type": "date" },

      "external_ids": {
        "type": "object",
        "dynamic": "strict",
        "properties": {
          "youtube_channel_id": { "type": "keyword" },
          "instagram_username": { "type": "keyword" },
          "twitter_username": { "type": "keyword" },
          "website_domain": { "type": "keyword" }
        }
      },

      "notes": { "type": "text" }
    }
  }
}
```

___

Deterministic _id: link:<creator_id>:<account_id>

This is where you store:

- confidence score

- reasons/signals that justify the link

- when it was created/updated

- (optional) "human approved” flag

```json
PUT creator-account-links
{
  "settings": { "number_of_shards": 1, "number_of_replicas": 1 },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "link_id": { "type": "keyword" },

      "creator_id": { "type": "keyword" }, 
      "account_id": { "type": "keyword" }, 

      "confidence": { "type": "float" },  
      "status": { "type": "keyword" },    

      "signals": {
        "type": "nested",
        "dynamic": "strict",
        "properties": {
          "type": { "type": "keyword" },   
          "value": { "type": "keyword" },  
          "weight": { "type": "float" }    
        }
      },

      "evidence": {
        "type": "object",
        "dynamic": "strict",
        "properties": {
          "matched_domains": { "type": "keyword" },
          "matched_youtube_channel_ids": { "type": "keyword" },
          "bio_similarity": { "type": "float" },
          "handle_similarity": { "type": "float" }
        }
      },

      "created_at": { "type": "date" },
      "updated_at": { "type": "date" },

      "approved": { "type": "boolean" },
      "approved_by": { "type": "keyword" },
      "approved_at": { "type": "date" }
    }
  }
}
```
___

# Templates

## 1.1 - Componment template: common settings:

```json
PUT _component_template/ct_common_settings_v1
{
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 1
    }
  },
  "_meta": {
    "name": "ct_common_settings_v1",
    "version": 1
  }
}
```

## 1.2 Component template: `creator-entities` mappings

```json
PUT _component_template/ct_creator_entities_mappings_v1
{
  "template": {
    "mappings": {
      "dynamic": "strict",
      "properties": {
        "creator_id": { "type": "keyword" },
        "canonical_name": { "type": "keyword" },
        "type": { "type": "keyword" },
        "aliases": { "type": "keyword" },

        "created_at": { "type": "date" },
        "updated_at": { "type": "date" },

        "external_ids": {
          "type": "object",
          "dynamic": "strict",
          "properties": {
            "youtube_channel_id": { "type": "keyword" },
            "instagram_username": { "type": "keyword" },
            "twitter_username": { "type": "keyword" },
            "website_domain": { "type": "keyword" }
          }
        },

        "notes": { "type": "text" }
      }
    }
  },
  "_meta": {
    "name": "ct_creator_entities_mappings_v1",
    "version": 1
  }
}

```

## 1.3 Component template: `creator-accounts` mappings

> Deterministic _id will be: tiktok:<uploader_id> for TikTok accounts.

```json
PUT _component_template/ct_creator_accounts_mappings_v1
{
  "template": {
    "mappings": {
      "dynamic": "strict",
      "properties": {
        "account_id": { "type": "keyword" },
        "platform": { "type": "keyword" },
        "platform_account_id": { "type": "keyword" },

        "handle": { "type": "keyword" },
        "display_name": { "type": "keyword" },
        "profile_url": { "type": "keyword" },

        "status": { "type": "keyword" },
        "first_seen": { "type": "date" },
        "last_seen": { "type": "date" },

        "signals": {
          "type": "object",
          "dynamic": "strict",
          "properties": {
            "website_domains": { "type": "keyword" },
            "youtube_channel_ids": { "type": "keyword" },
            "instagram_usernames": { "type": "keyword" },
            "twitter_usernames": { "type": "keyword" },
            "emails": { "type": "keyword" }
          }
        },

        "updated_at": { "type": "date" }
      }
    }
  },
  "_meta": {
    "name": "ct_creator_accounts_mappings_v1",
    "version": 1
  }
}
```

## 1.4 Component template: `creator-account-links` mappings

```json
PUT _component_template/ct_creator_account_links_mappings_v1
{
  "template": {
    "mappings": {
      "dynamic": "strict",
      "properties": {
        "link_id": { "type": "keyword" },

        "creator_id": { "type": "keyword" },
        "account_id": { "type": "keyword" },

        "confidence": { "type": "float" },
        "status": { "type": "keyword" },

        "signals": {
          "type": "nested",
          "dynamic": "strict",
          "properties": {
            "type": { "type": "keyword" },
            "value": { "type": "keyword" },
            "weight": { "type": "float" }
          }
        },

        "evidence": {
          "type": "object",
          "dynamic": "strict",
          "properties": {
            "matched_domains": { "type": "keyword" },
            "matched_youtube_channel_ids": { "type": "keyword" },
            "bio_similarity": { "type": "float" },
            "handle_similarity": { "type": "float" }
          }
        },

        "created_at": { "type": "date" },
        "updated_at": { "type": "date" },

        "approved": { "type": "boolean" },
        "approved_by": { "type": "keyword" },
        "approved_at": { "type": "date" }
      }
    }
  },
  "_meta": {
    "name": "ct_creator_account_links_mappings_v1",
    "version": 1
  }
}
```

## 1.5 Index templates (bind component templates to index names)

### `creator entities` Index Template
```json
PUT _index_template/it_creator_entities_v1
{
  "index_patterns": ["creator-entities"],
  "composed_of": [
    "ct_common_settings_v1",
    "ct_creator_entities_mappings_v1"
  ],
  "priority": 200,
  "_meta": { "name": "it_creator_entities_v1", "version": 1 }
}
```

### `creator-accounts` index template

```json
PUT _index_template/it_creator_accounts_v1
{
  "index_patterns": ["creator-accounts"],
  "composed_of": [
    "ct_common_settings_v1",
    "ct_creator_accounts_mappings_v1"
  ],
  "priority": 200,
  "_meta": { "name": "it_creator_accounts_v1", "version": 1 }
}
```

### `creator-account-links` index template

```json
PUT _index_template/it_creator_account_links_v1
{
  "index_patterns": ["creator-account-links"],
  "composed_of": [
    "ct_common_settings_v1",
    "ct_creator_account_links_mappings_v1"
  ],
  "priority": 200,
  "_meta": { "name": "it_creator_account_links_v1", "version": 1 }
}
```