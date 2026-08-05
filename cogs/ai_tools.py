POS_AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ban_user",
            "description": "Банит пользователя на сервере.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Discord ID пользователя, которого нужно забанить."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Причина бана."
                    }
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "unban_user",
            "description": "Разбанивает пользователя на сервере.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Discord ID пользователя, которого нужно разбанить."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Причина разбана."
                    }
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "timeout_user",
            "description": "Выдает тайм-аут (мут) пользователю.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Discord ID пользователя."
                    },
                    "minutes": {
                        "type": "string",
                        "description": "Длительность тайм-аута в минутах (например, '10' или '30')."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Причина мута."
                    }
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_role",
            "description": "Назначает уже существующую роль конкретному пользователю. Не создаёт новую роль сервера; для создания используй create_role.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Discord ID пользователя."
                    },
                    "role_id_or_name": {
                        "type": "string",
                        "description": "ID роли или точное имя роли."
                    }
                },
                "required": ["user_id", "role_id_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_role",
            "description": "Снимает уже существующую роль с конкретного пользователя. Не удаляет саму роль сервера; для удаления используй delete_role.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Discord ID пользователя."
                    },
                    "role_id_or_name": {
                        "type": "string",
                        "description": "ID роли или точное имя роли."
                    }
                },
                "required": ["user_id", "role_id_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_role",
            "description": "Создаёт новый объект роли на сервере. Не назначает роль пользователю; для назначения существующей роли используй add_role.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Название новой роли."
                    },
                    "color": {
                        "type": "string",
                        "description": "Необязательно. Цвет роли в HEX, например 'ff0000' или '#3498db'."
                    },
                    "hoist": {
                        "type": "string",
                        "description": "Необязательно. 'true', если роль должна отображаться отдельно в списке участников."
                    },
                    "mentionable": {
                        "type": "string",
                        "description": "Необязательно. 'true', если роль можно упоминать."
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_role",
            "description": "Полностью удаляет роль с сервера (не путать с remove_role, который снимает роль с пользователя).",
            "parameters": {
                "type": "object",
                "properties": {
                    "role_id_or_name": {
                        "type": "string",
                        "description": "ID или имя роли, которую нужно удалить с сервера."
                    }
                },
                "required": ["role_id_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_messages",
            "description": "Удаляет указанное количество последних сообщений в текущем канале.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "string",
                        "description": "Сколько последних сообщений удалить (от 1 до 100)."
                    }
                },
                "required": ["count"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_role",
            "description": "Изменяет обычную существующую роль: имя, цвет, отображение отдельно (hoist), упоминаемость, позицию и Discord-права. Можно отдельно добавить или снять права, включая снятие всех. Роль интеграции/бота с managed=true Discord API не разрешает редактировать; для неё используй права канала или действие с самим ботом.",
            "parameters": {
                "type": "object",
                "properties": {
                    "role_id_or_name": {"type": "string", "description": "ID или имя роли, которую нужно изменить."},
                    "new_name": {"type": "string", "description": "Необязательно. Новое название роли."},
                    "color": {"type": "string", "description": "Необязательно. Новый цвет в HEX, например 'ff0000' или '#3498db'."},
                    "hoist": {"type": "string", "description": "Необязательно. 'true'/'false' — отображать ли роль отдельно в списке участников."},
                    "mentionable": {"type": "string", "description": "Необязательно. 'true'/'false' — можно ли упоминать роль."},
                    "position": {"type": "string", "description": "Необязательно. Новая позиция в иерархии (целое число, чем больше — тем выше)."},
                    "permissions": {"type": "string", "description": "Совместимость: список прав через запятую, которые нужно добавить."},
                    "grant_permissions": {"type": "string", "description": "Необязательно. Права discord.py через запятую, которые нужно добавить, например 'manage_messages, kick_members'."},
                    "revoke_permissions": {"type": "string", "description": "Необязательно. Права discord.py через запятую, которые нужно снять. Значение 'all' снимает все права роли."}
                },
                "required": ["role_id_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_channel",
            "description": "Создаёт новый канал на сервере: текстовый, голосовой или категорию.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Название нового канала."},
                    "type": {"type": "string", "description": "Тип канала: text|announcement|voice|stage|category|forum|media. По умолчанию text."},
                    "category_id_or_name": {"type": "string", "description": "Необязательно. Точный ID или полное имя категории из запроса пользователя; не сокращай имя до общего слова вроде 'каналы'."},
                    "topic": {"type": "string", "description": "Необязательно. Описание (topic) для текстового канала."}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_channel",
            "description": "Удаляет канал или категорию с сервера. Это необратимо.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "ID или имя канала/категории, который нужно удалить."}
                },
                "required": ["channel_id_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_channel",
            "description": "Изменяет настройки канала: имя, тему (topic), медленный режим (slowmode), NSFW, перемещение в категорию.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "ID или имя канала, который нужно изменить."},
                    "new_name": {"type": "string", "description": "Необязательно. Новое имя канала."},
                    "topic": {"type": "string", "description": "Необязательно. Новое описание (topic)."},
                    "slowmode_seconds": {"type": "string", "description": "Необязательно. Медленный режим в секундах (0 — выключить, до 21600)."},
                    "nsfw": {"type": "string", "description": "Необязательно. 'true'/'false' — пометить канал как NSFW."},
                    "category_id_or_name": {"type": "string", "description": "Необязательно. Переместить канал в эту категорию (ID или имя)."},
                    "position": {"type": "string", "description": "Необязательно. Новая позиция канала внутри списка/категории, начиная с 0."}
                },
                "required": ["channel_id_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_channel_permission",
            "description": "Настраивает доступ роли или пользователя к каналу: открыть или закрыть просмотр/отправку сообщений.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "ID или имя канала."},
                    "target_role_or_user": {"type": "string", "description": "ID или имя роли, либо ID пользователя, для которого настраивается доступ."},
                    "allow": {"type": "string", "description": "'true' — открыть доступ (просмотр+отправка), 'false' — закрыть."}
                },
                "required": ["channel_id_or_name", "target_role_or_user", "allow"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kick_user",
            "description": "Выгоняет (кикает) пользователя с сервера. В отличие от бана, он сможет вернуться по приглашению.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Discord ID пользователя."},
                    "reason": {"type": "string", "description": "Причина кика."}
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_nickname",
            "description": "Меняет никнейм пользователя на сервере. Пустое значение сбрасывает ник к имени аккаунта.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Discord ID пользователя."},
                    "nickname": {"type": "string", "description": "Новый никнейм. Пусто — сбросить."}
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_invite",
            "description": "Создаёт приглашение (invite) на сервер. Действует 24 часа. По умолчанию — текущий сервер; владелец может указать любой сервер, где есть P.OS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "server_id_or_name": {"type": "string", "description": "Необязательно. ID или название сервера, на который создать приглашение (из числа серверов, где есть P.OS). Если не указан — текущий сервер."},
                    "channel_id_or_name": {"type": "string", "description": "Необязательно. Канал, для которого создать приглашение. Если не указан — берётся первый доступный."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_servers",
            "description": "Возвращает список серверов (гильдий), где присутствует P.OS, с названиями, ID и числом участников. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "setup_logging",
            "description": "Создаёт на текущем сервере систему логов: категорию и набор каналов для логирования (модерация, сообщения, участники, роли, каналы, голос и т.д.), видимых только администраторам. Если что-то уже создано — дополняет недостающее и чинит права. Вызывать ТОЛЬКО когда об этом прямо попросили.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category_name": {
                        "type": "string",
                        "description": "Необязательно. Название категории логов. По умолчанию 'логи'."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "untimeout_user",
            "description": "Снимает тайм-аут (мут) с пользователя досрочно.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Discord ID пользователя."},
                    "reason": {"type": "string", "description": "Необязательно. Причина снятия мута."}
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Отправляет сообщение от имени P.OS в указанный канал (можно на другом сервере, где есть P.OS). Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "ID или имя канала, куда отправить сообщение."},
                    "text": {"type": "string", "description": "Текст сообщения."},
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер назначения (ID или имя). Если не указан — текущий сервер."}
                },
                "required": ["channel_id_or_name", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_settings",
            "description": "Показывает текущие настройки модерации и поведения P.OS на сервере. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_settings",
            "description": (
                "Изменяет настройки модерации/безопасности P.OS на сервере. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение. "
                "Передавай только те поля, которые нужно изменить. Булевы ключи (true/false): "
                "enabled, filter_ads, filter_spam, filter_flood, filter_scam, filter_nsfw, filter_raid, "
                "filter_mention_spam, filter_crosschannel, ai_moderation, allow_profanity, log_messages, log_reactions. "
                "Числовые ключи: spam_window_seconds, spam_duplicates_threshold, flood_window_seconds, "
                "flood_messages_threshold, mention_limit, raid_join_window_seconds, raid_join_threshold, "
                "raid_mode_cooldown_seconds, min_account_age_hours, timeout_hours, crosschannel_window_seconds, "
                "crosschannel_channels_threshold. Строковый ключ raid_action: alert|quarantine|kick|ban. "
                "Маты и оскорбления разрешены по умолчанию (allow_profanity=true) и не модерируются."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "settings_json": {"type": "string", "description": "JSON-объект с изменяемыми настройками, например {\"filter_flood\": false, \"spam_duplicates_threshold\": 6}."},
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": ["settings_json"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ping_user",
            "description": "Пингует пользователя в канале с реальным уведомлением. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Discord ID пользователя, которого пингнуть."},
                    "text": {"type": "string", "description": "Необязательно. Текст сообщения рядом с пингом."},
                    "channel_id_or_name": {"type": "string", "description": "Необязательно. Канал для пинга. Если не указан — текущий канал."},
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "dm_user",
            "description": "Отправляет ЛС пользователю от имени P.OS. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Discord ID пользователя, которому написать в ЛС."},
                    "text": {"type": "string", "description": "Текст личного сообщения."}
                },
                "required": ["user_id", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lift_restrictions",
            "description": "Снимает ограничения с пользователя (тайм-аут/карантин/роль-мут) и уведомляет его в ЛС. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Discord ID пользователя, с которого снять ограничения."},
                    "reason": {"type": "string", "description": "Необязательно. Причина снятия."},
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "deactivate_raid_mode",
            "description": "Снимает режим рейда на сервере. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "leave_server",
            "description": "P.OS покидает указанный сервер. Необратимо. Команда Пумбы после code-level проверки выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "server_id_or_name": {"type": "string", "description": "ID или имя сервера, который нужно покинуть."}
                },
                "required": ["server_id_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shutdown_bot",
            "description": "Полностью останавливает P.OS (завершает работу процесса бота). ТОЛЬКО для владельца, требует подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Необязательно. Причина остановки."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mute_ai_for_user",
            "description": (
                "Добавляет пользователя в постоянный игнор P.OS на выбранном сервере: "
                "после фактической записи P.OS перестаёт отвечать этому пользователю. "
                "Используй по смыслу просьб владельца перестать замечать, игнорировать, "
                "не слушать или больше не отвечать конкретному участнику. Это не Discord mute."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Discord ID пользователя."
                    }
                },
                "required": ["user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "unmute_ai_for_user",
            "description": (
                "Полностью удаляет пользователя из постоянного игнора P.OS на выбранном "
                "сервере и снова разрешает ему получать ответы. Используй по смыслу просьб "
                "владельца вернуть ответы, перестать игнорировать, вынести/убрать из игнора "
                "или восстановить общение. Это не снятие Discord timeout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Discord ID пользователя."
                    }
                },
                "required": ["user_id"]
            }
        }
    }
]


POS_AI_TOOLS.extend([
    {
        "type": "function",
        "function": {
            "name": "runtime_status",
            "description": (
                "Возвращает владельцу проверяемый статус реально запущенной сборки "
                "P.OS: версию, Railway commit SHA и доступность основных AI, медиа- "
                "и веб-возможностей. Не угадывает и не раскрывает секреты."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_server",
            "description": "Изменяет базовые настройки сервера: название, описание, уровень проверки, фильтр контента, режим уведомлений. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Необязательно. Новое название сервера."},
                    "description": {"type": "string", "description": "Необязательно. Новое описание сервера."},
                    "verification_level": {"type": "string", "description": "Необязательно: none|low|medium|high|highest."},
                    "explicit_content_filter": {"type": "string", "description": "Необязательно: disabled|no_role|all_members."},
                    "default_notifications": {"type": "string", "description": "Необязательно: all_messages|only_mentions."},
                    "reason": {"type": "string", "description": "Необязательно. Причина изменения."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lock_channel",
            "description": "Закрывает канал для @everyone или указанной роли/пользователя: просмотр, отправку сообщений или оба права. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "ID или имя канала."},
                    "target_role_or_user": {"type": "string", "description": "Необязательно. Роль/пользователь. Если пусто — @everyone."},
                    "mode": {"type": "string", "description": "view|send|both. По умолчанию both."},
                    "reason": {"type": "string", "description": "Необязательно. Причина блокировки."}
                },
                "required": ["channel_id_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "unlock_channel",
            "description": "Снимает запрет просмотра/отправки сообщений в канале для @everyone или указанной роли/пользователя. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "ID или имя канала."},
                    "target_role_or_user": {"type": "string", "description": "Необязательно. Роль/пользователь. Если пусто — @everyone."},
                    "mode": {"type": "string", "description": "view|send|both. По умолчанию both."},
                    "reason": {"type": "string", "description": "Необязательно. Причина разблокировки."}
                },
                "required": ["channel_id_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_thread",
            "description": "Создаёт ветку в текстовом канале или от конкретного сообщения. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "ID или имя текстового канала."},
                    "name": {"type": "string", "description": "Название ветки."},
                    "message_id": {"type": "string", "description": "Необязательно. ID сообщения, от которого создать ветку."},
                    "private": {"type": "string", "description": "Необязательно. true — приватная ветка, false — публичная."},
                    "reason": {"type": "string", "description": "Необязательно. Причина создания."}
                },
                "required": ["channel_id_or_name", "name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "archive_thread",
            "description": "Архивирует/разархивирует и при необходимости блокирует/разблокирует ветку. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "ID или имя ветки."},
                    "archived": {"type": "string", "description": "true/false. По умолчанию true."},
                    "locked": {"type": "string", "description": "Необязательно. true/false — заблокировать ветку."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."}
                },
                "required": ["channel_id_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "voice_action",
            "description": "Выполняет действие с участником в голосе: disconnect, mute, unmute, deafen, undeafen, move. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Discord ID пользователя."},
                    "action": {"type": "string", "description": "disconnect|mute|unmute|deafen|undeafen|move."},
                    "channel_id_or_name": {"type": "string", "description": "Для move: ID или имя голосового канала назначения."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."}
                },
                "required": ["user_id", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "security_scan",
            "description": "Проводит быстрый аудит безопасности сервера: права P.OS, настройки модерации, raid mode, публичные каналы и рискованные роли. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "description": "summary|channels|roles|moderation|all. По умолчанию summary."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_security_preset",
            "description": "Применяет профиль безопасности P.OS: normal, strict или raid. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "preset": {"type": "string", "description": "normal|strict|raid."},
                    "reason": {"type": "string", "description": "Необязательно. Почему включается профиль."}
                },
                "required": ["preset"]
            }
        }
    },
])

POS_AI_TOOLS.extend([
    {
        "type": "function",
        "function": {
            "name": "list_bans",
            "description": "Показывает фактический бан-лист выбранного сервера с Discord ID и причинами. Только для Пумбы.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "string", "description": "Количество записей, 1-100; по умолчанию 25."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_threads",
            "description": "Показывает фактические активные ветки сервера, их родителей и состояние.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_poll",
            "description": "Создаёт нативный Discord-опрос в точном канале. Не имитирует опрос текстом.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "Точный канал для опроса."},
                    "question": {"type": "string", "description": "Вопрос опроса."},
                    "answers": {"type": "string", "description": "От 2 до 10 вариантов, каждый с новой строки или через точку с запятой."},
                    "duration_hours": {"type": "string", "description": "Длительность в часах, 1-168; по умолчанию 24."},
                    "allow_multiselect": {"type": "string", "description": "true/false: можно ли выбрать несколько вариантов."},
                },
                "required": ["channel_id_or_name", "question", "answers"],
            },
        },
    },
])


# Contextual control tools. They intentionally have no model-provided target:
# undo resolves exact IDs from the trusted execution journal, Telegram forwards
# the current Discord message, and vacation mode is bound to Pumba in code.
POS_AI_TOOLS.extend([
    {
        "type": "function",
        "function": {
            "name": "undo_recent_actions",
            "description": (
                "Отменяет последнюю группу реально выполненных P.OS действий из "
                "структурированного журнала. Используй для контекстных просьб вроде "
                "'верни всё обратно', 'отмени это', 'сделай как было'. Не выбирай "
                "ban/unban/kick и не угадывай пользователя заново."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "within_minutes": {
                        "type": "string",
                        "description": "Необязательно. Искать последнюю группу за 1-1440 минут; по умолчанию 30.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "contact_pumba_telegram",
            "description": (
                "Безопасно передаёт Пумбе в рабочий Telegram точный текущий запрос "
                "Discord-пользователя. Используй только когда пользователь явно просит "
                "написать, передать или связаться с Пумбой через Telegram. Текст, адрес "
                "и срочность код берёт сам; аргументы не нужны."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enable_vacation_mode",
            "description": (
                "Включает постоянный режим отпуска Пумбы. Используй только когда "
                "сам Пумба явно просит активировать или включить режим отпуска. "
                "После включения P.OS отвечает на пинги Пумбы и предлагает связаться "
                "с ним через Telegram. Аргументы не нужны."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disable_vacation_mode",
            "description": (
                "Выключает постоянный режим отпуска Пумбы. Используй только когда "
                "сам Пумба явно просит отключить, деактивировать или завершить режим "
                "отпуска. Аргументы не нужны."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vacation_mode_status",
            "description": (
                "Проверяет фактическое состояние режима отпуска Пумбы. Используй "
                "только когда Пумба спрашивает, включён ли режим отпуска. Аргументы "
                "не нужны."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
])

POS_AI_TOOLS.extend([
    {
        "type": "function",
        "function": {
            "name": "list_channels",
            "description": "Показывает фактическую структуру каналов сервера с типами, категориями и Discord ID. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_threads": {"type": "string", "description": "true/false. Включить активные ветки."},
                    "limit": {"type": "string", "description": "Сколько объектов вернуть, 1-100."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_roles",
            "description": "Показывает фактические роли сервера с Discord ID, позицией, числом участников и ключевыми правами. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "string", "description": "Сколько ролей вернуть, 1-100."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_audit_log",
            "description": "Читает фактический Discord Audit Log: действие, исполнитель, цель, время и причина. Можно фильтровать по названию действия. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Необязательно. Фильтр, например ban, role, channel, kick."},
                    "limit": {"type": "string", "description": "Сколько записей вернуть, 1-50."},
                },
                "required": [],
            },
        },
    },
])

POS_AI_TOOLS.extend([
    {
        "type": "function",
        "function": {
            "name": "list_members",
            "description": "Показывает фактический список участников сервера с username/login, display name и ID. Можно фильтровать по query или роли. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Необязательно. Часть username/login/global/display для поиска."},
                    "role_id_or_name": {"type": "string", "description": "Необязательно. Показать только участников с этой ролью."},
                    "limit": {"type": "string", "description": "Необязательно. Сколько показать, 1-50."},
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "user_info",
            "description": "Показывает фактическую карточку участника: username/login, display/global, ID, роли, ключевые права, даты, timeout. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Discord ID, mention или username/login пользователя."},
                    "user_identifier": {"type": "string", "description": "Username/login/global/display пользователя, если ID неизвестен."},
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_messages",
            "description": "Читает последние сообщения в указанном канале (или текущем канале) с фактическими message_id, авторами и временем. Можно фильтровать по тексту и автору. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "ID или имя канала. Для другого сервера обязательно."},
                    "limit": {"type": "string", "description": "Сколько сообщений вернуть, 1-50."},
                    "query": {"type": "string", "description": "Необязательно. Фильтр по тексту сообщения."},
                    "user_identifier": {"type": "string", "description": "Необязательно. Фильтр по автору: ID, mention или username/login."},
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_logs",
            "description": "Ищет фактические события в журнале P.OS: серверные логи, действия P.OS, сообщения, удаления и пинги. Не выдумывает, возвращает только найденное. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Необязательно. Поиск по summary/details/actor."},
                    "event_type": {"type": "string", "description": "Необязательно. Например pos_tool, message_mention, log:members, log:message_deletes, log:security."},
                    "limit": {"type": "string", "description": "Сколько событий вернуть, 1-50."},
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_pings",
            "description": "Ищет, кто пинговал пользователя напрямую или через роль, которая у него есть. Находит даже удалённые сообщения, если P.OS видел исходный пинг. ТОЛЬКО для владельца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Discord ID, mention или username/login. Если пусто и спрашивает владелец — ищет пинги владельца."},
                    "user_identifier": {"type": "string", "description": "Username/login/global/display пользователя, если ID неизвестен."},
                    "include_roles": {"type": "string", "description": "true/false. По умолчанию true — учитывать пинги ролей пользователя."},
                    "limit": {"type": "string", "description": "Сколько событий вернуть, 1-50."},
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bulk_user_action",
            "description": "Выполняет массовое действие по списку username/login/ID: ban, kick, timeout, untimeout, add_role, remove_role, lift_restrictions. Команда Пумбы выполняется сразу; запрос другого участника отправляется Пумбе на подтверждение.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "ban|kick|timeout|untimeout|add_role|remove_role|lift_restrictions."},
                    "user_identifiers": {"type": "string", "description": "Список пользователей: username/login/ID/mentions через запятую, пробел или с новой строки."},
                    "role_id_or_name": {"type": "string", "description": "Для add_role/remove_role: ID или имя роли."},
                    "minutes": {"type": "string", "description": "Для timeout: минуты."},
                    "reason": {"type": "string", "description": "Необязательно. Причина действия."},
                    "server_id_or_name": {"type": "string", "description": "Необязательно. Сервер (ID или имя). Если не указан — текущий."}
                },
                "required": ["action", "user_identifiers"]
            }
        }
    },
])

POS_AI_TOOLS.extend([
    {
        "type": "function",
        "function": {
            "name": "research_web",
            "description": (
                "Ищет актуальную информацию в публичном интернете, безопасно читает "
                "несколько источников и возвращает ответ только с фактическими ссылками. "
                "При отсутствии Brave Search использует ограниченный Wikipedia fallback. "
                "ТОЛЬКО для владельца."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Что именно найти или проверить в интернете.",
                    },
                    "max_sources": {
                        "type": "string",
                        "description": "Необязательно. Число источников от 1 до 4.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_web_page",
            "description": (
                "Безопасно читает указанную публичную HTTPS-страницу, защищаясь от "
                "SSRF, опасных перенаправлений и prompt injection в содержимом. "
                "Возвращает фактический ответ со ссылкой. ТОЛЬКО для владельца."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Полный публичный HTTPS URL страницы.",
                    },
                    "question": {
                        "type": "string",
                        "description": "Необязательно. Что именно узнать со страницы.",
                    },
                },
                "required": ["url"],
            },
        },
    },
])

POS_AI_TOOLS.extend([
    {
        "type": "function",
        "function": {
            "name": "manage_message",
            "description": "Редактирует собственное сообщение P.OS, удаляет, закрепляет, открепляет, публикует announcement или завершает poll по фактическому ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "edit|delete|pin|unpin|publish|end_poll."},
                    "channel_id_or_name": {"type": "string", "description": "Точный канал сообщения."},
                    "message_id": {"type": "string", "description": "Discord ID сообщения."},
                    "text": {"type": "string", "description": "Новый текст для edit."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."},
                },
                "required": ["action", "channel_id_or_name", "message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_reaction",
            "description": "Добавляет реакцию P.OS либо очищает выбранную/все реакции конкретного сообщения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "add|remove_pos|clear|clear_all."},
                    "channel_id_or_name": {"type": "string", "description": "Точный канал сообщения."},
                    "message_id": {"type": "string", "description": "Discord ID сообщения."},
                    "emoji": {"type": "string", "description": "Unicode emoji или Discord custom emoji."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."},
                },
                "required": ["action", "channel_id_or_name", "message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_invites",
            "description": "Читает фактический список активных приглашений сервера.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revoke_invite",
            "description": "Отзывает существующее приглашение по коду или URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invite_code_or_url": {"type": "string", "description": "Код либо полный Discord invite URL."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."},
                },
                "required": ["invite_code_or_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_webhooks",
            "description": "Читает фактические webhook сервера без раскрытия токенов.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_webhook",
            "description": "Удаляет webhook по точному ID или имени.",
            "parameters": {
                "type": "object",
                "properties": {
                    "webhook_id_or_name": {"type": "string", "description": "Точный ID или уникальное имя webhook."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."},
                },
                "required": ["webhook_id_or_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_automod_rules",
            "description": "Читает фактические правила Discord AutoMod и их статус.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_automod_rule",
            "description": "Создаёт keyword/mention-spam правило Discord AutoMod, включает, отключает, переименовывает или удаляет его.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "create_keyword|create_mention_spam|enable|disable|rename|delete."},
                    "rule_id_or_name": {"type": "string", "description": "Для существующего правила: точный ID или имя."},
                    "name": {"type": "string", "description": "Имя нового правила либо новое имя."},
                    "keywords": {"type": "string", "description": "Ключевые слова через запятую или новую строку."},
                    "regex_patterns": {"type": "string", "description": "Необязательно. Regex-паттерны через новую строку."},
                    "allow_list": {"type": "string", "description": "Необязательно. Исключения через запятую."},
                    "mention_limit": {"type": "string", "description": "Для mention-spam: лимит упоминаний 1-50."},
                    "mention_raid_protection": {"type": "string", "description": "true/false."},
                    "enabled": {"type": "string", "description": "true/false; по умолчанию true."},
                    "alert_channel_id_or_name": {"type": "string", "description": "Необязательно. Канал системных оповещений."},
                    "timeout_minutes": {"type": "string", "description": "Необязательно. Тайм-аут нарушителя."},
                    "custom_message": {"type": "string", "description": "Необязательно. Сообщение блокировки."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scheduled_events",
            "description": "Читает фактические запланированные события сервера.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_scheduled_event",
            "description": "Создаёт, изменяет, запускает, завершает, отменяет или удаляет Discord Scheduled Event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "create|edit|start|complete|cancel|delete."},
                    "event_id_or_name": {"type": "string", "description": "Для существующего события: ID или точное имя."},
                    "name": {"type": "string", "description": "Название события."},
                    "description": {"type": "string", "description": "Необязательно. Описание."},
                    "start_time": {"type": "string", "description": "ISO 8601 с часовым поясом."},
                    "end_time": {"type": "string", "description": "Необязательно. ISO 8601."},
                    "event_type": {"type": "string", "description": "external|voice|stage."},
                    "location": {"type": "string", "description": "Место для external."},
                    "channel_id_or_name": {"type": "string", "description": "Voice/stage канал."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_forum_post",
            "description": "Создаёт новый пост в Discord ForumChannel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id_or_name": {"type": "string", "description": "Точный форумный канал."},
                    "name": {"type": "string", "description": "Заголовок поста."},
                    "text": {"type": "string", "description": "Первое сообщение поста."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."},
                },
                "required": ["channel_id_or_name", "name", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_server_safety",
            "description": "Управляет нативной защитой Discord: паузой инвайтов/ЛС, raid alerts и safety alerts channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invites_disabled": {"type": "string", "description": "true/false — отключить обычные инвайты."},
                    "invites_disabled_minutes": {"type": "string", "description": "Временно отключить инвайты на 1-1440 минут."},
                    "dms_disabled_minutes": {"type": "string", "description": "Временно отключить DMs на 1-1440 минут."},
                    "raid_alerts_enabled": {"type": "string", "description": "true/false — включены ли Discord raid alerts."},
                    "safety_alerts_channel_id_or_name": {"type": "string", "description": "Канал нативных safety-уведомлений."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_emojis",
            "description": "Читает фактический список пользовательских эмодзи сервера.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_emoji",
            "description": "Создаёт эмодзи из вложения текущего сообщения, переименовывает или удаляет его.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "create|rename|delete."},
                    "emoji_id_or_name": {"type": "string", "description": "Для rename/delete: ID или точное имя."},
                    "name": {"type": "string", "description": "Имя нового/переименованного эмодзи."},
                    "attachment_index": {"type": "string", "description": "Для create: индекс вложения текущего сообщения, начиная с 0."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_stickers",
            "description": "Читает фактический список стикеров сервера.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_sticker",
            "description": "Создаёт стикер из вложения текущего сообщения, изменяет или удаляет его.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "create|edit|delete."},
                    "sticker_id_or_name": {"type": "string", "description": "Для edit/delete: ID или точное имя."},
                    "name": {"type": "string", "description": "Имя стикера."},
                    "description": {"type": "string", "description": "Описание стикера."},
                    "emoji": {"type": "string", "description": "Связанный Unicode emoji/tag."},
                    "attachment_index": {"type": "string", "description": "Для create: индекс вложения текущего сообщения, начиная с 0."},
                    "reason": {"type": "string", "description": "Необязательно. Причина."},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": "Сохраняет предоставленный владельцем факт или рабочую запись в постоянной базе P.OS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Короткий заголовок записи."},
                    "text": {"type": "string", "description": "Точный текст записи без домыслов."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_memory_entries",
            "description": "Читает фактические записи постоянной базы P.OS.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "string", "description": "Количество записей, 1-50."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_memory_entry",
            "description": "Удаляет точную запись постоянной базы P.OS по ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "Числовой ID записи."},
                },
                "required": ["entry_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "refresh_server_memory",
            "description": "Собирает свежий контекст из доступной истории каналов выбранного сервера в память P.OS.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
])


# 0.8: кросс-серверность. Владелец может выполнять управляющие действия на любом
# сервере, где есть P.OS, не находясь на нём. Добавляем необязательный параметр
# server_id_or_name ко всем гильдийным инструментам (если его там ещё нет), чтобы
# модель знала о такой возможности. Резолвинг сервера выполняется в pos_ai.
_CROSS_SERVER_TOOLS = {
    "ban_user", "unban_user", "timeout_user", "untimeout_user", "kick_user", "set_nickname",
    "add_role", "remove_role", "create_role", "delete_role", "edit_role",
    "create_channel", "delete_channel", "edit_channel", "set_channel_permission",
    "lock_channel", "unlock_channel", "create_thread", "archive_thread",
    "edit_server", "voice_action", "security_scan", "set_security_preset",
    "create_invite", "delete_messages", "setup_logging", "send_message",
    "get_settings", "update_settings", "dm_user", "mute_ai_for_user", "unmute_ai_for_user",
    "list_members", "user_info", "read_messages", "search_logs", "search_pings", "bulk_user_action",
    "list_channels", "list_roles", "read_audit_log",
    "ping_user", "lift_restrictions", "deactivate_raid_mode",
    "manage_message", "manage_reaction", "list_invites", "revoke_invite",
    "list_webhooks", "delete_webhook", "list_automod_rules", "manage_automod_rule",
    "list_scheduled_events", "manage_scheduled_event", "create_forum_post",
    "set_server_safety", "list_emojis", "manage_emoji", "list_stickers",
    "manage_sticker",
    "refresh_server_memory",
    "list_bans", "list_threads", "send_poll",
}

_USER_IDENTIFIER_TOOLS = {
    "ban_user", "unban_user", "timeout_user", "untimeout_user", "kick_user", "set_nickname",
    "add_role", "remove_role", "voice_action", "ping_user", "dm_user", "lift_restrictions",
    "mute_ai_for_user", "unmute_ai_for_user",
}

def _inject_cross_server_param(tools: list) -> None:
    for tool in tools:
        fn = tool.get("function", {})
        if fn.get("name") in _CROSS_SERVER_TOOLS:
            params = fn.setdefault("parameters", {})
            props = params.setdefault("properties", {})
            props.setdefault(
                "server_id_or_name",
                {
                    "type": "string",
                    "description": "Необязательно. Сервер (ID или имя), на котором выполнить действие. Если не указан — текущий. Для Пумбы выполняется сразу; запрос другого участника на другой сервер ждёт подтверждения Пумбы.",
                },
            )


_inject_cross_server_param(POS_AI_TOOLS)


def _inject_user_identifier_param(tools: list) -> None:
    for tool in tools:
        fn = tool.get("function", {})
        if fn.get("name") not in _USER_IDENTIFIER_TOOLS:
            continue
        params = fn.setdefault("parameters", {})
        props = params.setdefault("properties", {})
        if "user_id" in props:
            props["user_id"]["description"] = (
                props["user_id"].get("description", "Пользователь.")
                + " Можно передать ID, mention или username/login; код проверит фактического участника."
            )
        props.setdefault(
            "user_identifier",
            {
                "type": "string",
                "description": "Необязательно. Username/login/global/display пользователя, если ID неизвестен.",
            },
        )
        required = params.get("required") or []
        if "user_id" in required:
            params["required"] = [item for item in required if item != "user_id"]


_inject_user_identifier_param(POS_AI_TOOLS)


_TOOL_FIELD_MAX_LENGTHS = {
    "reason": 512,
    "text": 1900,
    "topic": 1024,
    "name": 100,
    "new_name": 100,
    "nickname": 32,
    "query": 500,
    "question": 500,
    "url": 2048,
    "max_sources": 2,
    "settings_json": 8000,
    "user_identifiers": 5000,
    "answers": 1000,
    "position": 8,
}


def _harden_tool_schemas(tools: list) -> None:
    """Make provider hints match the code-level tool boundary.

    Providers may ignore parts of JSON Schema, so runtime validation remains
    mandatory in pos_ai.execute_pos_tool. These constraints still reduce
    malformed calls and prevent the model from inventing hidden parameters.
    """
    for tool in tools:
        function = tool.get("function", {})
        parameters = function.get("parameters", {})
        if parameters.get("type") != "object":
            continue
        parameters["additionalProperties"] = False
        properties = parameters.get("properties", {})
        for field_name, field_schema in properties.items():
            if not isinstance(field_schema, dict) or field_schema.get("type") != "string":
                continue
            field_schema.setdefault(
                "maxLength",
                _TOOL_FIELD_MAX_LENGTHS.get(field_name, 512),
            )


_harden_tool_schemas(POS_AI_TOOLS)
