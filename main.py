import json
import os
import time
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from astrbot.api import star
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.provider import ProviderRequest
from astrbot.api import logger
from astrbot.core.star.star_tools import StarTools
from astrbot.core.message.message_event_result import MessageChain


class Main(star.Star):
    def __init__(self, context: star.Context, config: dict):
        super().__init__(context)
        self.config = config
        
        # 获取配置
        self.max_history = config.get("max_history", 15)
        self.storage_mode = config.get("storage_mode", "conventional")
        self.互通_scope = config.get("互通_scope", "none")
        self.platform_isolation = config.get("platform_isolation", True)
        self.inject_position = config.get("inject_position", "system")
        self.time_format = config.get("time_format", "%m-%d %H:%M")
        self.debug_mode = config.get("debug_mode", False)
        self.log_max_length = config.get("log_max_length", 500)
        self.cleanup_on_terminate = config.get("cleanup_on_terminate", False)
        
        # 数据目录
        self.data_dir = StarTools.get_data_dir("shared_memory")
        os.makedirs(self.data_dir, exist_ok=True)
        
        logger.info(f"[SharedMemory] 插件已初始化，模式: {self.storage_mode}, 互通: {self.互通_scope}, 隔离: {self.platform_isolation}, 调试: {self.debug_mode}, 自动清理: {self.cleanup_on_terminate}")

    def _truncate_text(self, text: str, max_len: int = None) -> str:
        """截断文本，避免日志过长"""
        if max_len is None:
            max_len = self.log_max_length
        if not text:
            return "[空]"
        if len(text) <= max_len:
            return text
        return text[:max_len] + f"...[截断，共{len(text)}字符]"

    def _get_bot_instance_id(self, event: AstrMessageEvent) -> str:
        """获取Bot实例ID（区分不同的OneBot/QQ号）"""
        if self.platform_isolation:
            self_id = str(event.get_self_id())
            return self_id
        else:
            return "shared"

    def _get_memory_file_path(self, bot_instance: str, chat_type: str, user_id: str = None) -> str:
        """获取记忆文件路径"""
        instance_dir = os.path.join(self.data_dir, bot_instance)
        os.makedirs(instance_dir, exist_ok=True)
        
        if self.storage_mode == "simple" and user_id:
            return os.path.join(instance_dir, f"{chat_type}_user_{user_id}.json")
        else:
            return os.path.join(instance_dir, f"{chat_type}_shared.json")

    def _load_memories(self, file_path: str) -> List[Dict]:
        """加载记忆文件"""
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[SharedMemory] 加载记忆文件失败: {e}")
            return []

    def _save_memories(self, file_path: str, memories: List[Dict]):
        """保存记忆文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(memories, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[SharedMemory] 保存记忆文件失败: {e}")

    def _get_all_memories_with_source(self, bot_instance: str) -> List[Tuple[Dict, str, str]]:
        """
        获取该Bot实例的所有记忆，附带来源信息
        返回: [(memory_entry, chat_type, file_path), ...]
        """
        all_memories = []
        
        instance_dir = os.path.join(self.data_dir, bot_instance)
        if not os.path.exists(instance_dir):
            return []
        
        for filename in os.listdir(instance_dir):
            if not filename.endswith('.json'):
                continue
            
            file_path = os.path.join(instance_dir, filename)
            
            if filename.startswith('private_'):
                chat_type = 'private'
            elif filename.startswith('group_'):
                chat_type = 'group'
            else:
                continue
            
            memories = self._load_memories(file_path)
            for mem in memories:
                all_memories.append((mem, chat_type, file_path))
        
        all_memories.sort(key=lambda x: x[0].get("timestamp", 0), reverse=True)
        return all_memories

    def _should_store_chat_type(self, chat_type: str) -> bool:
        """根据互通配置决定是否应该存储该类型的聊天"""
        if self.互通_scope == "none":
            return True
        elif self.互通_scope == "private":
            return chat_type == "private"
        elif self.互通_scope == "group":
            return chat_type == "group"
        elif self.互通_scope == "all":
            return True
        return True

    def _get_inject_memories(self, event: AstrMessageEvent) -> List[Dict]:
        """获取需要注入的记忆"""
        bot_instance = self._get_bot_instance_id(event)
        is_private = event.is_private_chat()
        current_chat_type = "private" if is_private else "group"
        
        memories_to_inject = []
        
        load_types = []
        if self.互通_scope == "none":
            load_types = [current_chat_type]
        elif self.互通_scope == "private":
            if is_private:
                load_types = ["private"]
        elif self.互通_scope == "group":
            if not is_private:
                load_types = ["group"]
        elif self.互通_scope == "all":
            load_types = ["private", "group"]
        
        user_id = str(event.get_sender_id()) if self.storage_mode == "simple" else None
        
        for chat_type in load_types:
            if self.storage_mode == "simple" and user_id:
                file_path = self._get_memory_file_path(bot_instance, chat_type, user_id)
                memories = self._load_memories(file_path)
                memories_to_inject.extend(memories)
            else:
                file_path = self._get_memory_file_path(bot_instance, chat_type)
                memories = self._load_memories(file_path)
                memories_to_inject.extend(memories)
        
        memories_to_inject.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return memories_to_inject[:self.max_history]

    def _format_memory_prompt(self, memories: List[Dict]) -> str:
        """将记忆格式化为提示词文本"""
        if not memories:
            return ""
        
        lines = ["【历史记忆】以下是你与其他用户的最近对话记录："]
        
        for mem in reversed(memories):
            time_str = datetime.fromtimestamp(mem.get("timestamp", 0)).strftime(self.time_format)
            user_name = mem.get("user_name", "未知用户")
            user_msg = mem.get("user_msg", "")
            bot_response = mem.get("bot_response", "")
            chat_type = "私聊" if mem.get("chat_type") == "private" else "群聊"
            
            line = f"[{time_str}] [{chat_type}] {user_name}: {user_msg}"
            if bot_response:
                line += f" → 你回复: {bot_response}"
            lines.append(line)
        
        lines.append("【记忆结束】请根据以上记忆自然地回应当前对话。")
        return "\n".join(lines)

    @filter.on_llm_request()
    async def inject_memory(self, event: AstrMessageEvent, req: ProviderRequest):
        """在LLM请求前注入记忆"""
        status = "跳过"
        inject_info = "无"
        
        try:
            is_private = event.is_private_chat()
            chat_type_str = "私聊" if is_private else "群聊"
            bot_id = event.get_self_id()
            user_id = event.get_sender_id()
            
            if self.debug_mode:
                logger.info(f"[SharedMemory] ========== 记忆注入开始 ==========")
                logger.info(f"[SharedMemory] [会话] Bot:{bot_id} | 用户:{user_id} | 类型:{chat_type_str}")
                logger.info(f"[SharedMemory] [注入前] system_prompt长度: {len(req.system_prompt) if req.system_prompt else 0}")
                logger.info(f"[SharedMemory] [注入前] contexts数量: {len(req.contexts) if req.contexts else 0}")
                if req.system_prompt:
                    logger.info(f"[SharedMemory] [注入前system内容]: {self._truncate_text(req.system_prompt)}")
            
            should_inject = False
            if self.互通_scope == "all":
                should_inject = True
                inject_info = "全部互通模式"
            elif self.互通_scope == "private" and is_private:
                should_inject = True
                inject_info = "仅私聊互通"
            elif self.互通_scope == "group" and not is_private:
                should_inject = True
                inject_info = "仅群聊互通"
            elif self.互通_scope == "none":
                should_inject = True
                inject_info = "同类型互通"
            
            if not should_inject:
                status = "跳过(配置限制)"
                if self.debug_mode:
                    logger.info(f"[SharedMemory] [状态] {status} - 当前配置不允许此类聊天注入")
                    logger.info(f"[SharedMemory] ========== 记忆注入结束 ==========")
                return
            
            memories = self._get_inject_memories(event)
            
            if not memories:
                status = "跳过(无记忆)"
                if self.debug_mode:
                    logger.info(f"[SharedMemory] [状态] {status} - 未找到可注入的历史记忆")
                    logger.info(f"[SharedMemory] ========== 记忆注入结束 ==========")
                return
            
            memory_prompt = self._format_memory_prompt(memories)
            
            if self.debug_mode:
                logger.info(f"[SharedMemory] [注入内容] 共{len(memories)}条记忆")
                logger.info(f"[SharedMemory] [注入内容详情]: {self._truncate_text(memory_prompt)}")
            
            if self.inject_position == "system":
                original_len = len(req.system_prompt) if req.system_prompt else 0
                if req.system_prompt:
                    req.system_prompt += f"\n\n{memory_prompt}"
                else:
                    req.system_prompt = memory_prompt
                new_len = len(req.system_prompt)
                
                status = f"成功注入system({len(memories)}条)"
                
                if self.debug_mode:
                    logger.info(f"[SharedMemory] [注入后] system_prompt长度: {new_len} (增加{new_len-original_len})")
                    logger.info(f"[SharedMemory] [注入后system内容]: {self._truncate_text(req.system_prompt)}")
            else:
                original_count = len(req.contexts) if req.contexts else 0
                memory_message = {"role": "user", "content": memory_prompt}
                if req.contexts:
                    req.contexts.insert(0, memory_message)
                else:
                    req.contexts = [memory_message]
                new_count = len(req.contexts)
                
                status = f"成功注入contexts({len(memories)}条)"
                
                if self.debug_mode:
                    logger.info(f"[SharedMemory] [注入后] contexts数量: {new_count} (增加{new_count-original_count})")
                    logger.info(f"[SharedMemory] [注入后第一条消息]: {self._truncate_text(str(req.contexts[0]))}")
            
            logger.info(f"[SharedMemory] [状态] {status} | {inject_info} | Bot:{bot_id} | 用户:{user_id} | 类型:{chat_type_str}")
            
            if self.debug_mode:
                logger.info(f"[SharedMemory] ========== 记忆注入结束 ==========")
                
        except Exception as e:
            status = f"失败({str(e)})"
            logger.error(f"[SharedMemory] [状态] {status}")
            logger.error(f"[SharedMemory] 注入记忆时出错: {e}")
            if self.debug_mode:
                import traceback
                logger.error(f"[SharedMemory] 错误详情: {traceback.format_exc()}")

    @filter.after_message_sent()
    async def store_memory(self, event: AstrMessageEvent):
        """在消息发送后存储对话记录"""
        try:
            is_private = event.is_private_chat()
            chat_type = "private" if is_private else "group"
            chat_type_str = "私聊" if is_private else "群聊"
            
            if not self._should_store_chat_type(chat_type):
                if self.debug_mode:
                    logger.info(f"[SharedMemory] [存储跳过] 配置不允许存储{chat_type_str}消息")
                return
            
            user_msg = event.get_message_str()
            if not user_msg:
                return
            
            bot_instance = self._get_bot_instance_id(event)
            user_id = str(event.get_sender_id())
            user_name = event.get_sender_name() or "未知用户"
            session_id = event.get_session_id()
            
            result = event.get_result()
            bot_response = ""
            if result and result.chain:
                texts = []
                for comp in result.chain:
                    if hasattr(comp, 'text'):
                        texts.append(comp.text)
                bot_response = " ".join(texts)
            
            memory_entry = {
                "timestamp": time.time(),
                "user_id": user_id,
                "user_name": user_name,
                "user_msg": user_msg,
                "bot_response": bot_response[:500],
                "chat_type": chat_type,
                "platform": event.get_platform_name(),
                "bot_instance": bot_instance,
                "session_id": session_id
            }
            
            if self.storage_mode == "simple":
                file_path = self._get_memory_file_path(bot_instance, chat_type, user_id)
            else:
                file_path = self._get_memory_file_path(bot_instance, chat_type)
            
            memories = self._load_memories(file_path)
            memories.append(memory_entry)
            
            if len(memories) > self.max_history:
                memories = memories[-self.max_history:]
            
            self._save_memories(file_path, memories)
            
            if self.debug_mode:
                logger.info(f"[SharedMemory] [存储成功] {chat_type_str} | Bot:{bot_instance} | 用户:{user_name}({user_id}) | 内容:{self._truncate_text(user_msg, 100)} | 总计:{len(memories)}条")
            else:
                logger.debug(f"[SharedMemory] 已存储记忆到 {file_path}, 当前共 {len(memories)} 条 [Bot: {bot_instance}]")
            
        except Exception as e:
            logger.error(f"[SharedMemory] 存储记忆时出错: {e}")
            if self.debug_mode:
                import traceback
                logger.error(f"[SharedMemory] 错误详情: {traceback.format_exc()}")

    @filter.command_group("memory")
    def memory_group(self):
        """记忆管理命令组"""
        pass

    @memory_group.command("list")
    async def memory_list(self, event: AstrMessageEvent, page: int = 1):
        """
        查看所有记忆列表（支持分页）
        用法: /memory list [页码]
        """
        if not event.is_admin():
            await event.send(MessageChain().message("权限不足，仅管理员可使用此命令。"))
            return
        
        bot_instance = self._get_bot_instance_id(event)
        all_memories = self._get_all_memories_with_source(bot_instance)
        
        if not all_memories:
            await event.send(MessageChain().message(f"当前Bot实例 [{bot_instance}] 暂无记忆数据。"))
            return
        
        page_size = 10
        total = len(all_memories)
        total_pages = (total + page_size - 1) // page_size
        
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
        
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_memories = all_memories[start_idx:end_idx]
        
        lines = [f"📋 记忆列表 (Bot: {bot_instance})"]
        lines.append(f"第 {page}/{total_pages} 页，共 {total} 条记忆")
        lines.append("=" * 40)
        
        for idx, (mem, chat_type, file_path) in enumerate(page_memories, start=start_idx + 1):
            time_str = datetime.fromtimestamp(mem.get("timestamp", 0)).strftime(self.time_format)
            user_name = mem.get("user_name", "未知用户")
            user_msg = mem.get("user_msg", "")[:30]
            chat_type_str = "私聊" if chat_type == "private" else "群聊"
            
            is_user_memory = "user_" in os.path.basename(file_path)
            mode_str = "[个人]" if is_user_memory else "[共享]"
            
            line = f"{idx}. [{time_str}] {mode_str}[{chat_type_str}] {user_name}: {user_msg}"
            if len(mem.get("user_msg", "")) > 30:
                line += "..."
            lines.append(line)
        
        lines.append("=" * 40)
        lines.append("操作命令:")
        lines.append("• /memory list <页码> - 查看指定页")
        lines.append("• /memory delete <序号> - 删除指定记忆")
        lines.append("• /memory del_last - 删除最新一条")
        lines.append("• /memory clear - 清空所有记忆")
        
        await event.send(MessageChain().message("\n".join(lines)))

    @memory_group.command("delete")
    async def memory_delete(self, event: AstrMessageEvent, index: int):
        """
        删除指定序号的记忆
        用法: /memory delete <序号>
        """
        if not event.is_admin():
            await event.send(MessageChain().message("权限不足，仅管理员可使用此命令。"))
            return
        
        if index < 1:
            await event.send(MessageChain().message("序号必须大于0。"))
            return
        
        bot_instance = self._get_bot_instance_id(event)
        all_memories = self._get_all_memories_with_source(bot_instance)
        
        if not all_memories:
            await event.send(MessageChain().message("当前没有可删除的记忆。"))
            return
        
        if index > len(all_memories):
            await event.send(MessageChain().message(f"序号超出范围，当前共有 {len(all_memories)} 条记忆。"))
            return
        
        target_mem, chat_type, file_path = all_memories[index - 1]
        target_timestamp = target_mem.get("timestamp")
        target_user_id = target_mem.get("user_id")
        
        file_memories = self._load_memories(file_path)
        original_count = len(file_memories)
        
        file_memories = [
            m for m in file_memories 
            if not (m.get("timestamp") == target_timestamp and m.get("user_id") == target_user_id)
        ]
        
        if len(file_memories) < original_count:
            self._save_memories(file_path, file_memories)
            
            time_str = datetime.fromtimestamp(target_timestamp).strftime(self.time_format)
            chat_type_str = "私聊" if chat_type == "private" else "群聊"
            await event.send(MessageChain().message(
                f"✅ 已删除第 {index} 条记忆 [{time_str}] [{chat_type_str}] {target_mem.get('user_name', '未知')}: {self._truncate_text(target_mem.get('user_msg', ''), 50)}"
            ))
            
            logger.info(f"[SharedMemory] 管理员删除了记忆 #{index} from {file_path}")
        else:
            await event.send(MessageChain().message("❌ 删除失败，未找到匹配的记忆条目。"))

    @memory_group.command("del_last")
    async def memory_del_last(self, event: AstrMessageEvent):
        """删除最新的一条记忆"""
        if not event.is_admin():
            await event.send(MessageChain().message("权限不足，仅管理员可使用此命令。"))
            return
        
        bot_instance = self._get_bot_instance_id(event)
        all_memories = self._get_all_memories_with_source(bot_instance)
        
        if not all_memories:
            await event.send(MessageChain().message("当前没有可删除的记忆。"))
            return
        
        await self.memory_delete(event, 1)

    @memory_group.command("clear")
    async def memory_clear(self, event: AstrMessageEvent, confirm: str = ""):
        """
        清空所有记忆（危险操作）
        用法: /memory clear confirm 确认清空
        """
        if not event.is_admin():
            await event.send(MessageChain().message("权限不足，仅管理员可使用此命令。"))
            return
        
        if confirm.lower() != "confirm":
            await event.send(MessageChain().message(
                "⚠️ 警告：此操作将删除当前Bot实例的所有记忆且不可恢复！\n"
                "如需确认清空，请执行: /memory clear confirm"
            ))
            return
        
        bot_instance = self._get_bot_instance_id(event)
        instance_dir = os.path.join(self.data_dir, bot_instance)
        
        if os.path.exists(instance_dir):
            import shutil
            shutil.rmtree(instance_dir)
            logger.info(f"[SharedMemory] 管理员清空了Bot实例 {bot_instance} 的所有记忆")
            await event.send(MessageChain().message(f"✅ 已清空Bot实例 [{bot_instance}] 的所有记忆数据。"))
        else:
            await event.send(MessageChain().message(f"当前Bot实例 [{bot_instance}] 没有记忆数据。"))

    @memory_group.command("uninstall")
    async def memory_uninstall(self, event: AstrMessageEvent, confirm: str = ""):
        """
        清理所有数据并准备卸载（需要手动删除目录）
        用法: /memory uninstall confirm
        """
        if not event.is_admin():
            await event.send(MessageChain().message("权限不足，仅管理员可使用此命令。"))
            return
        
        bot_instance = self._get_bot_instance_id(event)
        instance_dir = os.path.join(self.data_dir, bot_instance)
        
        if confirm.lower() != "confirm":
            msg = "⚠️ 准备卸载插件，此操作将：\n"
            msg += f"1. 清空 Bot [{bot_instance}] 的所有记忆数据\n"
            msg += "2. 你需要手动删除插件目录才能重新安装\n\n"
            
            if os.path.exists(instance_dir):
                count = len(self._get_all_memories_with_source(bot_instance))
                msg += f"📊 当前共有 {count} 条记忆将被删除\n"
            
            msg += "🔴 执行请发送: /memory uninstall confirm\n"
            msg += "💡 提示：你也可以在配置中开启'停用插件时自动清理数据'"
            await event.send(MessageChain().message(msg))
            return
        
        # 执行清理
        if os.path.exists(instance_dir):
            import shutil
            shutil.rmtree(instance_dir)
        
        # 清理主数据目录（如果是最后一个Bot实例）
        if os.path.exists(self.data_dir):
            remaining = [d for d in os.listdir(self.data_dir) if os.path.isdir(os.path.join(self.data_dir, d))]
            if not remaining or (len(remaining) == 1 and remaining[0] == bot_instance):
                try:
                    shutil.rmtree(self.data_dir)
                except:
                    pass
        
        await event.send(MessageChain().message(
            "✅ 数据已清空！请继续以下步骤完成卸载：\n\n"
            "1️⃣ 进入 AstrBot WebUI → 插件管理\n"
            "2️⃣ 找到 shared_memory → 点击'卸载'\n"
            "3️⃣ SSH执行：\n"
            f"   rm -rf /AstrBot/data/plugins/shared_memory/\n"
            "4️⃣ 重新上传安装新版\n\n"
            "或者直接点击'重载插件'来更新（如果目录已替换）"
        ))
        
        logger.info(f"[SharedMemory] 管理员执行卸载清理 for Bot {bot_instance}")

    @memory_group.command("status")
    async def memory_status(self, event: AstrMessageEvent):
        """查看记忆状态统计"""
        if not event.is_admin():
            await event.send(MessageChain().message("权限不足，仅管理员可使用此命令。"))
            return
        
        bot_instance = self._get_bot_instance_id(event)
        all_memories = self._get_all_memories_with_source(bot_instance)
        
        total = len(all_memories)
        private_count = sum(1 for _, t, _ in all_memories if t == "private")
        group_count = sum(1 for _, t, _ in all_memories if t == "group")
        
        user_counts = {}
        for mem, _, fp in all_memories:
            uid = mem.get("user_id", "unknown")
            uname = mem.get("user_name", "未知")
            key = f"{uname}({uid})"
            user_counts[key] = user_counts.get(key, 0) + 1
        
        lines = [f"📊 记忆统计 (Bot: {bot_instance})", "=" * 30]
        lines.append(f"总记忆数: {total}/{self.max_history * (2 if self.storage_mode == 'conventional' else 10)}")
        lines.append(f"私聊记忆: {private_count} 条")
        lines.append(f"群聊记忆: {group_count} 条")
        lines.append(f"存储模式: {'简洁模式(按用户隔离)' if self.storage_mode == 'simple' else '常规模式(共享)'}")
        lines.append(f"互通范围: {self.互通_scope}")
        lines.append(f"自动清理: {'⚠️ 开启' if self.cleanup_on_terminate else '关闭'}")
        
        if user_counts and self.storage_mode == "simple":
            lines.append("\n用户分布:")
            for user, count in sorted(user_counts.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"  • {user}: {count}条")
        
        lines.append("\n命令帮助:")
        lines.append("• /memory list - 查看记忆列表")
        lines.append("• /memory delete <序号> - 删除指定记忆")
        lines.append("• /memory del_last - 删除最新记忆")
        lines.append("• /memory clear confirm - 清空所有")
        lines.append("• /memory uninstall confirm - 卸载准备")
        
        await event.send(MessageChain().message("\n".join(lines)))

    async def terminate(self):
        """插件终止时清理"""
        if self.cleanup_on_terminate:
            try:
                import shutil
                if os.path.exists(self.data_dir):
                    shutil.rmtree(self.data_dir)
                    logger.info(f"[SharedMemory] ⚠️ 自动清理已启用，已删除数据目录: {self.data_dir}")
            except Exception as e:
                logger.error(f"[SharedMemory] 自动清理失败: {e}")
        
        logger.info("[SharedMemory] 插件已卸载")
