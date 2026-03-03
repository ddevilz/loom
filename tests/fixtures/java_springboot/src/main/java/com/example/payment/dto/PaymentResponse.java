package com.example.payment.dto;

import com.example.payment.domain.Payment;
import com.example.payment.domain.PaymentStatus;
import com.example.payment.domain.PaymentType;
import java.math.BigDecimal;

public class PaymentResponse {
    private String id;
    private PaymentType type;
    private BigDecimal amount;
    private String currency;
    private PaymentStatus status;

    public static PaymentResponse from(Payment payment) {
        PaymentResponse response = new PaymentResponse();
        response.id = payment.getId();
        response.type = payment.getType();
        response.amount = payment.getAmount();
        response.status = payment.getStatus();
        return response;
    }

    // Getters and setters
    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public PaymentType getType() { return type; }
    public void setType(PaymentType type) { this.type = type; }
    public BigDecimal getAmount() { return amount; }
    public void setAmount(BigDecimal amount) { this.amount = amount; }
    public PaymentStatus getStatus() { return status; }
    public void setStatus(PaymentStatus status) { this.status = status; }
}
