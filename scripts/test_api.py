"""
测试API连接

测试DashScope（千问）和DeepSeek的API连接
"""

import os
import sys


def test_dashscope_api():
    """测试DashScope API（千问）"""
    print("=" * 60)
    print("测试 DashScope API（千问）")
    print("=" * 60)

    try:
        from openai import OpenAI

        # 直接从环境变量读取
        api_key = os.getenv("MEDAGENT_DASHSCOPE_API_KEY")
        base_url = os.getenv("MEDAGENT_DASHSCOPE_COMPATIBLE_BASE_URL",
                            "https://dashscope.aliyuncs.com/compatible-mode/v1")
        model = os.getenv("MEDAGENT_QWEN_TASK_MODEL", "qwen-plus")

        if not api_key:
            print("❌ 未找到DashScope API密钥")
            return False

        print(f"✅ API密钥: {api_key[:20]}...")
        print(f"✅ Base URL: {base_url}")
        print(f"✅ 模型: {model}")

        # 创建客户端
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        # 测试调用
        print("\n发送测试请求...")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "你好，请回复'连接成功'"}
            ],
            max_tokens=50,
        )

        reply = response.choices[0].message.content
        print(f"✅ 收到响应: {reply}")

        if "成功" in reply or "你好" in reply:
            print("✅ DashScope API 连接成功！")
            return True
        else:
            print("⚠️  收到响应但内容异常")
            return False

    except Exception as e:
        print(f"❌ DashScope API 连接失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_deepseek_api():
    """测试DeepSeek API"""
    print("\n" + "=" * 60)
    print("测试 DeepSeek API")
    print("=" * 60)

    try:
        from openai import OpenAI

        # 从环境变量读取
        api_key = os.getenv("MEDAGENT_DEEPSEEK_API_KEY")
        base_url = os.getenv("MEDAGENT_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

        if not api_key:
            print("❌ 未找到DeepSeek API密钥")
            return False

        print(f"✅ API密钥: {api_key[:20]}...")
        print(f"✅ Base URL: {base_url}")

        # 创建客户端
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        # 测试调用
        print("\n发送测试请求...")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": "你好，请回复'连接成功'"}
            ],
            max_tokens=50,
        )

        reply = response.choices[0].message.content
        print(f"✅ 收到响应: {reply}")

        if "成功" in reply or "你好" in reply:
            print("✅ DeepSeek API 连接成功！")
            return True
        else:
            print("⚠️  收到响应但内容异常")
            return False

    except Exception as e:
        print(f"❌ DeepSeek API 连接失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("开始测试API连接...")
    print()

    # 加载.env文件
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ 已加载 .env 配置文件")
        print()
    except ImportError:
        print("⚠️  python-dotenv未安装，使用系统环境变量")
        print()

    # 测试两个API
    dashscope_ok = test_dashscope_api()
    deepseek_ok = test_deepseek_api()

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"DashScope (千问): {'✅ 成功' if dashscope_ok else '❌ 失败'}")
    print(f"DeepSeek:         {'✅ 成功' if deepseek_ok else '❌ 失败'}")
    print()

    if dashscope_ok and deepseek_ok:
        print("🎉 所有API连接正常！")
        return 0
    else:
        print("⚠️  部分API连接失败，请检查：")
        print("  1. API密钥是否正确")
        print("  2. 网络连接是否正常")
        print("  3. API余额是否充足")
        return 1


if __name__ == "__main__":
    sys.exit(main())
