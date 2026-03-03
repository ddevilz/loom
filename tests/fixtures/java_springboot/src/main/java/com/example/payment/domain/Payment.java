package com.example.payment.domain;

import java.math.BigDecimal;
import java.time.LocalDateTime;

public abstract class Payment {
    private String id;
    private BigDecimal amount;
    private String currency;
    private PaymentStatus status;
    private LocalDateTime createdAt;

    public Payment(String id, BigDecimal amount, String currency) {
        this.id = id;
        this.amount = amount;
        this.currency = currency;
        this.status = PaymentStatus.PENDING;
        this.createdAt = LocalDateTime.now();
    }

    public abstract PaymentType getType();
    
    public abstract boolean validate();
    
    public void process() {
        if (validate()) {
            this.status = PaymentStatus.PROCESSING;
        }
    }

    public String getId() {
        return id;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public PaymentStatus getStatus() {
        return status;
    }

    protected void setStatus(PaymentStatus status) {
        this.status = status;
    }
}
