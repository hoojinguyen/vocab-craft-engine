"""
Scenario Tree Builder for English Dataset System Engine.
Constructs branching interactive dialogue trees (dialogue_trees and dialogue_nodes).
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ScenarioBuilder:
    """Builds interactive branching dialogue trees for situational practice."""

    def __init__(self):
        pass

    def create_scenario_tree(self, title: str, topic: str, cefr_level: str = "B1") -> Dict[str, Any]:
        """
        Initializes a scenario tree metadata payload.
        """
        return {
            "title": title,
            "topic": topic,
            "cefr_level": cefr_level,
            "nodes": []
        }

    def add_node(
        self,
        tree_id: int,
        speaker_role: str,
        sentence_id: Optional[int],
        parent_node_id: Optional[int] = None,
        choice_label: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates a single dialogue node in the branching graph.
        """
        return {
            "tree_id": tree_id,
            "parent_node_id": parent_node_id,
            "choice_label": choice_label,
            "speaker_role": speaker_role,  # "A" (Bot/Partner) or "B" (User)
            "sentence_id": sentence_id
        }

    def build_all_scenarios(self) -> List[Dict[str, Any]]:
        """
        Generates 25+ structured branching situational scenarios across 8 themes:
        Dining, Travel & Directions, Hotel & Accommodation, Shopping & Retail,
        Work & Business, Social & Greetings, Healthcare & Medical, Daily Conversation.
        """
        return [
            # --- Dining (4 scenarios) ---
            {
                "title": "Ordering Coffee at a Cafe",
                "topic": "Dining",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Hi! What can I get started for you today?",
                        "text_vi": "Xin chào! Bạn muốn gọi món gì hôm nay?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Order a Hot Latte",
                        "text_en": "I'd like a hot latte, please.",
                        "text_vi": "Cho tôi một ly latte nóng."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Order an Iced Coffee",
                        "text_en": "Just an iced Americano for me, thanks.",
                        "text_vi": "Cho tôi một ly Americano đá, cảm ơn."
                    },
                    {
                        "node_index": 3,
                        "parent_index": 1,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Sure thing! What size would you like?",
                        "text_vi": "Chắc chắn rồi! Bạn muốn dùng size nào?"
                    }
                ]
            },
            {
                "title": "Reserving a Table at a Restaurant",
                "topic": "Dining",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Good evening! Welcome to Bistro Bella. Do you have a reservation?",
                        "text_vi": "Buổi tối vui vẻ! Chào mừng tới Bistro Bella. Bạn đã đặt bàn trước chưa?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Confirm Reservation",
                        "text_en": "Yes, under the name Alex for two at 7 PM.",
                        "text_vi": "Có, tên Alex cho 2 người lúc 7 giờ tối."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Walk-in Request",
                        "text_en": "No, we don't. Is there a table available for two?",
                        "text_vi": "Chưa, chúng tôi chưa đặt. Còn bàn cho 2 người không?"
                    }
                ]
            },
            {
                "title": "Asking for the Check",
                "topic": "Dining",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "How was everything with your meal today?",
                        "text_vi": "Bữa ăn của bạn hôm nay thế nào?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Compliment & Request Bill",
                        "text_en": "It was delicious! Could we get the check, please?",
                        "text_vi": "Rất ngon! Cho chúng tôi xin hóa đơn nhé?"
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Ask about Payment Options",
                        "text_en": "Everything was great. Do you accept credit cards?",
                        "text_vi": "Mọi thứ tuyệt vời. Ở đây có nhận thẻ tín dụng không?"
                    }
                ]
            },
            {
                "title": "Dietary Restrictions & Substitutions",
                "topic": "Dining",
                "cefr_level": "B2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Are you ready to order, or do you need a few more minutes?",
                        "text_vi": "Bạn đã sẵn sàng gọi món chưa, hay cần thêm vài phút?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Ask for Gluten-free options",
                        "text_en": "Could you tell me if this dish contains gluten?",
                        "text_vi": "Bạn có thể cho tôi biết món này có chứa gluten không?"
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Request Vegetarian modification",
                        "text_en": "Can I get the burger with a plant-based patty instead?",
                        "text_vi": "Cho tôi gọi burger thay bằng nhân chay được không?"
                    }
                ]
            },

            # --- Travel & Directions (4 scenarios) ---
            {
                "title": "Asking for Directions to Subway",
                "topic": "Travel & Directions",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Excuse me, do you know where the subway station is?",
                        "text_vi": "Xin lỗi, bạn có biết ga tàu điện ngầm ở đâu không?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Give directions",
                        "text_en": "Go straight for two blocks, it's on your left.",
                        "text_vi": "Đi thẳng 2 dãy nhà, nó ở bên tay trái bạn."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Polite decline",
                        "text_en": "Sorry, I'm not from around here.",
                        "text_vi": "Xin lỗi, tôi không phải người ở đây."
                    }
                ]
            },
            {
                "title": "Buying Train Tickets at the Station",
                "topic": "Travel & Directions",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Next in line! Where are you traveling to today?",
                        "text_vi": "Người tiếp theo! Bạn muốn đi đâu hôm nay?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "One-way ticket",
                        "text_en": "One one-way ticket to Central Station, please.",
                        "text_vi": "Cho tôi một vé một chiều đến Ga Trung Tâm."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Round-trip ticket",
                        "text_en": "I'd like a round-trip ticket to Oxford for tomorrow.",
                        "text_vi": "Cho tôi một vé khứ hồi đi Oxford vào ngày mai."
                    }
                ]
            },
            {
                "title": "Lost in an Airport Terminal",
                "topic": "Travel & Directions",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "May I help you? You look a bit lost.",
                        "text_vi": "Tôi có thể giúp gì cho bạn? Trông bạn có vẻ bối rối."
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Ask for Gate B12",
                        "text_en": "Yes, please. Which direction is Gate B12?",
                        "text_vi": "Vâng, cho hỏi Cổng B12 đi hướng nào?"
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Baggage Claim Location",
                        "text_en": "Could you tell me where Baggage Claim is?",
                        "text_vi": "Bạn chỉ cho tôi khu lấy hành lý ở đâu được không?"
                    }
                ]
            },
            {
                "title": "Renting a Car at the Airport",
                "topic": "Travel & Directions",
                "cefr_level": "B2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Welcome to Apex Car Rental! How can I assist you today?",
                        "text_vi": "Chào mừng đến với Apex Rent-a-Car! Tôi có thể giúp gì cho bạn?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Pickup Existing Reservation",
                        "text_en": "Hi, I have a reservation under the name Taylor.",
                        "text_vi": "Chào bạn, tôi có đặt xe trước tên Taylor."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Inquire about SUV Rental",
                        "text_en": "Do you have any full-size SUVs available for 3 days?",
                        "text_vi": "Bên bạn còn xe SUV cỡ lớn cho thuê 3 ngày không?"
                    }
                ]
            },

            # --- Hotel & Accommodation (3 scenarios) ---
            {
                "title": "Checking In at Hotel Front Desk",
                "topic": "Hotel & Accommodation",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Welcome to The Grand Hotel! How can I help you today?",
                        "text_vi": "Chào mừng quý khách đến khách sạn The Grand! Tôi có thể giúp gì?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Check-in with Reservation",
                        "text_en": "Hi, I'm checking in. The reservation is under Smith.",
                        "text_vi": "Chào bạn, tôi muốn nhận phòng. Tên đặt phòng là Smith."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Ask for Late Check-in",
                        "text_en": "Hi, we arrived late. Is our room still available?",
                        "text_vi": "Chào bạn, chúng tôi đến trễ. Phòng của chúng tôi vẫn còn chứ?"
                    }
                ]
            },
            {
                "title": "Requesting Hotel Amenities",
                "topic": "Hotel & Accommodation",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Front Desk, how may I direct your call?",
                        "text_vi": "Bộ phận Lễ tân nghe, tôi có thể giúp gì cho quý khách?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Ask for Extra Towels",
                        "text_en": "Could we get extra towels sent up to room 402?",
                        "text_vi": "Có thể gửi thêm khăn tắm lên phòng 402 được không?"
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Inquire about Breakfast",
                        "text_en": "What time is breakfast served in the morning?",
                        "text_vi": "Bữa sáng được phục vụ vào lúc mấy giờ?"
                    }
                ]
            },
            {
                "title": "Reporting an Issue with Room",
                "topic": "Hotel & Accommodation",
                "cefr_level": "B2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Good afternoon, Front Desk speaking.",
                        "text_vi": "Xin chào, Lễ tân xin nghe."
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Report AC Failure",
                        "text_en": "The air conditioning in room 310 isn't working.",
                        "text_vi": "Điều hòa ở phòng 310 không hoạt động."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Request Room Change",
                        "text_en": "The room has a strong smoke smell, can we change rooms?",
                        "text_vi": "Phòng có mùi thuốc lá nồng quá, chúng tôi đổi phòng được không?"
                    }
                ]
            },

            # --- Shopping & Retail (3 scenarios) ---
            {
                "title": "Trying On Clothes at a Boutique",
                "topic": "Shopping & Retail",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Hi there! Let me know if you need help finding any sizes.",
                        "text_vi": "Xin chào! Cần tìm size gì cứ báo mình nhé."
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Ask for Medium Size",
                        "text_en": "Do you have this jacket in a medium?",
                        "text_vi": "Áo khoác này có size M không ạ?"
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Ask for Fitting Room",
                        "text_en": "Where are the fitting rooms located?",
                        "text_vi": "Phòng thử đồ ở đâu vậy ạ?"
                    }
                ]
            },
            {
                "title": "Returning an Item with Receipt",
                "topic": "Shopping & Retail",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Hi, welcome to Customer Service. What can I do for you?",
                        "text_vi": "Xin chào! Dịch vụ khách hàng xin nghe. Tôi có thể giúp gì?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Request Full Refund",
                        "text_en": "I'd like to return this sweater; I have the receipt.",
                        "text_vi": "Tôi muốn trả lại chiếc áo đan này; tôi có hóa đơn."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Exchange for Color",
                        "text_en": "Can I exchange this shirt for a different color?",
                        "text_vi": "Tôi có thể đổi áo này sang màu khác được không?"
                    }
                ]
            },
            {
                "title": "Asking for Discounts & Deals",
                "topic": "Shopping & Retail",
                "cefr_level": "B2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Your total comes out to $145.00 today.",
                        "text_vi": "Tổng cộng của bạn hôm nay là 145 đô la."
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Ask about Store Coupon",
                        "text_en": "Is there any promotional code or store discount available?",
                        "text_vi": "Có mã giảm giá hay chương trình khuyến mãi nào áp dụng được không?"
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Inquire about Loyalty",
                        "text_en": "Do I get a discount if I sign up for the membership?",
                        "text_vi": "Đăng ký thành viên có được giảm giá không?"
                    }
                ]
            },

            # --- Work & Business (4 scenarios) ---
            {
                "title": "Introducing Yourself at a New Job",
                "topic": "Work & Business",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Hi everyone! This is Jordan, our new marketing coordinator.",
                        "text_vi": "Chào mọi người! Đây là Jordan, điều phối viên marketing mới của chúng ta."
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Friendly greeting",
                        "text_en": "Hi everyone, I'm really excited to join the team!",
                        "text_vi": "Chào mọi người, tôi rất vui khi được gia nhập đội ngũ!"
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Professional overview",
                        "text_en": "Hello all, looking forward to collaborating on future projects.",
                        "text_vi": "Xin chào mọi người, tôi rất mong được hợp tác trong các dự án tới."
                    }
                ]
            },
            {
                "title": "Scheduling a Business Meeting",
                "topic": "Work & Business",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "We need to discuss the quarterly financial targets.",
                        "text_vi": "Chúng ta cần thảo luận về các mục tiêu tài chính quý này."
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Propose Tuesday morning",
                        "text_en": "How about we meet on Tuesday at 10 AM in Conference Room B?",
                        "text_vi": "Thứ Ba lúc 10 sáng tại Phòng họp B thì sao?"
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Suggest Online Video Call",
                        "text_en": "Could we set up a Zoom call tomorrow afternoon instead?",
                        "text_vi": "Chúng ta tổ chức cuộc gọi Zoom vào chiều mai được không?"
                    }
                ]
            },
            {
                "title": "Giving a Project Status Update",
                "topic": "Work & Business",
                "cefr_level": "B2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Could you give us a quick status update on the software launch?",
                        "text_vi": "Bạn có thể cập nhật nhanh tiến độ ra mắt phần mềm không?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "On Schedule Status",
                        "text_en": "We are right on schedule and expect to release by Friday.",
                        "text_vi": "Chúng tôi đang đúng tiến độ và dự kiến ra mắt vào thứ Sáu."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Address Delay Risk",
                        "text_en": "We ran into minor testing issues, so we might delay by 2 days.",
                        "text_vi": "Chúng tôi gặp một chút vấn đề khi kiểm thử nên có thể chậm 2 ngày."
                    }
                ]
            },
            {
                "title": "Negotiating a Contract Term",
                "topic": "Work & Business",
                "cefr_level": "C1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "We reviewed your proposal, but the delivery timeline seems tight.",
                        "text_vi": "Chúng tôi đã xem đề xuất, nhưng thời hạn giao hàng hơi gấp."
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Offer Phased Delivery",
                        "text_en": "We can offer a phased rollout to meet your critical milestone.",
                        "text_vi": "Chúng tôi có thể triển khai theo từng giai đoạn để kịp mốc quan trọng."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Propose Adjusted Fee",
                        "text_en": "If we expedite the timeline, we need to adjust the overhead fee by 5%.",
                        "text_vi": "Nếu đẩy nhanh tiến độ, chúng tôi cần điều chỉnh 5% phí phụ trội."
                    }
                ]
            },

            # --- Social & Greetings (3 scenarios) ---
            {
                "title": "Meeting a Neighbor in the Elevator",
                "topic": "Social & Greetings",
                "cefr_level": "A1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Good morning! Cold weather today, isn't it?",
                        "text_vi": "Chào buổi sáng! Hôm nay trời lạnh thật nhỉ?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Agree about weather",
                        "text_en": "Yes, it really is! Don't forget your warm coat.",
                        "text_vi": "Đúng vậy! Đừng quên mặc áo ấm nhé."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Introduce yourself",
                        "text_en": "It sure is! By the way, I just moved into apartment 4B.",
                        "text_vi": "Lạnh thật! Nhân tiện, tôi mới chuyển vào căn hộ 4B."
                    }
                ]
            },
            {
                "title": "Attending a Birthday Party",
                "topic": "Social & Greetings",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Hey! So glad you could make it to the party!",
                        "text_vi": "Này! Rất vui vì bạn đã đến dự tiệc!"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Hand Over Gift",
                        "text_en": "Happy Birthday! Here's a small gift for you.",
                        "text_vi": "Chúc mừng sinh nhật! Có món quà nhỏ tặng bạn đây."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Ask about Drinks",
                        "text_en": "Thanks for having me! Where can I grab a drink?",
                        "text_vi": "Cảm ơn đã mời tôi! Tôi lấy đồ uống ở đâu nhỉ?"
                    }
                ]
            },
            {
                "title": "Making Weekend Plans with Friends",
                "topic": "Social & Greetings",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Do you have any plans for this coming weekend?",
                        "text_vi": "Cuối tuần này bạn có kế hoạch gì chưa?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Suggest Movie",
                        "text_en": "Not yet! Want to check out that new sci-fi movie?",
                        "text_vi": "Chưa! Có muốn đi xem phim viễn tưởng mới ra không?"
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Propose Outdoor Hike",
                        "text_en": "I was thinking of going hiking at the national park.",
                        "text_vi": "Tôi đang tính đi leo núi ở công viên quốc gia."
                    }
                ]
            },

            # --- Healthcare & Medical (3 scenarios) ---
            {
                "title": "Describing Symptoms to a Doctor",
                "topic": "Healthcare & Medical",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "What brings you in to see me today?",
                        "text_vi": "Hôm nay có lý do gì khiến bạn đến khám?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Describe Sore Throat & Fever",
                        "text_en": "I've had a severe sore throat and a mild fever since yesterday.",
                        "text_vi": "Tôi bị đau họng nặng và sốt nhẹ từ hôm qua."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Mention Back Pain",
                        "text_en": "I hurt my lower back while lifting heavy boxes.",
                        "text_vi": "Tôi bị đau lưng dưới khi bê đồ nặng."
                    }
                ]
            },
            {
                "title": "Picking Up Prescription at Pharmacy",
                "topic": "Healthcare & Medical",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Hello! How can I help you at the pharmacy today?",
                        "text_vi": "Xin chào! Tôi có thể giúp gì cho bạn tại nhà thuốc?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Provide Name for Prescription",
                        "text_en": "Hi, I'm picking up a prescription for Sarah Connor.",
                        "text_vi": "Chào bạn, tôi đến lấy thuốc theo đơn cho Sarah Connor."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Ask for Pain Reliever",
                        "text_en": "Can you recommend an over-the-counter pain reliever?",
                        "text_vi": "Bạn có thể giới thiệu thuốc giảm đau không cần kê đơn không?"
                    }
                ]
            },
            {
                "title": "Scheduling a Dental Appointment",
                "topic": "Healthcare & Medical",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Bright Smile Dental Clinic, how can I help you?",
                        "text_vi": "Nha khoa Bright Smile xin nghe, tôi giúp gì được cho bạn?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Request Routine Checkup",
                        "text_en": "I'd like to schedule a routine dental cleaning and checkup.",
                        "text_vi": "Tôi muốn đặt lịch khám và lấy cao răng định kỳ."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Emergency Toothache",
                        "text_en": "I have an urgent toothache. Is there any slot available today?",
                        "text_vi": "Tôi bị đau răng cấp tính. Hôm nay còn lịch trống nào không?"
                    }
                ]
            },

            # --- Daily Conversation (3 scenarios) ---
            {
                "title": "Discussing Favorite Movies",
                "topic": "Daily Conversation",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Have you seen any good movies recently?",
                        "text_vi": "Dạo này bạn có xem bộ phim nào hay không?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Recommend Action Film",
                        "text_en": "Yeah, I watched an amazing action film last weekend.",
                        "text_vi": "Có, cuối tuần trước tôi xem một bộ phim hành động tuyệt vời."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Mention Documentary",
                        "text_en": "I mostly watch tech documentaries on Netflix.",
                        "text_vi": "Tôi chủ yếu xem phim tài liệu công nghệ trên Netflix."
                    }
                ]
            },
            {
                "title": "Talking About Hobbies and Sports",
                "topic": "Daily Conversation",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "What do you usually like to do in your free time?",
                        "text_vi": "Bạn thường thích làm gì vào thời gian rảnh?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Mention Running",
                        "text_en": "I love going for a long run in the morning.",
                        "text_vi": "Tôi thích đi chạy bộ đường dài vào buổi sáng."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Mention Cooking",
                        "text_en": "I really enjoy trying out new recipes at home.",
                        "text_vi": "Tôi rất thích thử các công thức nấu ăn mới ở nhà."
                    }
                ]
            },
            {
                "title": "Reporting a Missing Item",
                "topic": "Daily Conversation",
                "cefr_level": "B2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Lost and Found department. How can I help you?",
                        "text_vi": "Bộ phận Tìm đồ thất lạc xin nghe. Tôi giúp gì được cho bạn?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Describe Lost Backpack",
                        "text_en": "I think I left a blue backpack on the bus this morning.",
                        "text_vi": "Tôi nghĩ tôi đã quên một chiếc balo màu xanh trên xe buýt sáng nay."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Inquire about Wallet",
                        "text_en": "Has anyone turned in a black leather wallet?",
                        "text_vi": "Có ai nhặt được và nộp lại một chiếc ví da màu đen không?"
                    }
                ]
            }
        ]

    def build_sample_scenarios(self) -> List[Dict[str, Any]]:
        """
        Generates sample branching dialogue scenarios for English learners.
        Each node contains text_en, text_vi, speaker_role, choice_label, and parent_index.
        """
        return self.build_all_scenarios()[:2]

